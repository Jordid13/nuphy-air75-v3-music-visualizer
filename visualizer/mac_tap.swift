// System-audio capture for macOS 14.2+ (Core Audio process tap), used by audio_source.py.
// Writes interleaved float32 stereo to stdout; exits when stdout closes. Nothing comes out until the Mac
// has played some sound since the helper started (the tap's clock only starts then); after that it streams,
// silence included.
// The first line on stderr is "rate <hz>", the tap's rate (the reader resamples if it isn't what it wants).
// Needs the System Audio Recording permission for the app that runs it (your terminal).
import AudioToolbox
import CoreAudio
import Foundation

func fail(_ msg: String, _ err: OSStatus = 0) -> Never {
    FileHandle.standardError.write("mac_tap: \(msg)\(err != 0 ? " (\(err))" : "")\n".data(using: .utf8)!)
    exit(1)
}
func address(_ sel: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal,
                               mElement: kAudioObjectPropertyElementMain)
}

let tapDesc = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
tapDesc.uuid = UUID()
tapDesc.isPrivate = true
tapDesc.muteBehavior = .unmuted
var tap = AudioObjectID(0)
var err = AudioHardwareCreateProcessTap(tapDesc, &tap)
if err != 0 { fail("can't create the system audio tap (needs macOS 14.2+)", err) }

// tap only: adding the output device as clock (as Apple's sample does) also mixes in that device's own
// inputs (e.g. a headset mic) and stalls while the output is idle
let aggDesc: [String: Any] = [
    kAudioAggregateDeviceNameKey: "nuphy-visualizer-tap",
    kAudioAggregateDeviceUIDKey: UUID().uuidString,
    kAudioAggregateDeviceIsPrivateKey: true,
    kAudioAggregateDeviceIsStackedKey: false,
    kAudioAggregateDeviceTapAutoStartKey: true,
    kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: tapDesc.uuid.uuidString,
                                       kAudioSubTapDriftCompensationKey: true]],
]
var agg = AudioObjectID(0)
err = AudioHardwareCreateAggregateDevice(aggDesc as CFDictionary, &agg)
if err != 0 { fail("can't create the capture device", err) }
var frames: UInt32 = 256  // the default 512 halves the visualizer's frame rate
var bufAddr = address(kAudioDevicePropertyBufferFrameSize)
AudioObjectSetPropertyData(agg, &bufAddr, 0, nil, 4, &frames)

var addr = address(kAudioTapPropertyFormat)
var format = AudioStreamBasicDescription()
var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
err = AudioObjectGetPropertyData(tap, &addr, 0, nil, &size, &format)
if err != 0 { fail("can't read the tap format", err) }
let interleaved = format.mFormatFlags & kAudioFormatFlagIsNonInterleaved == 0
FileHandle.standardError.write("rate \(Int(format.mSampleRate))\n".data(using: .utf8)!)

signal(SIGPIPE, SIG_DFL)  // reader gone -> exit; the tap and device are private, so they go with us
var proc: AudioDeviceIOProcID?
err = AudioDeviceCreateIOProcIDWithBlock(&proc, agg, nil) { _, input, _, _, _ in
    let bufs = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
    guard let first = bufs.first, first.mData != nil else { return }
    if interleaved {
        _ = write(1, first.mData!, Int(first.mDataByteSize))
        return
    }
    // planar -> interleaved stereo
    let n = Int(bufs[0].mDataByteSize) / 4
    let l = bufs[0].mData!.assumingMemoryBound(to: Float.self)
    let r = bufs[min(1, bufs.count - 1)].mData!.assumingMemoryBound(to: Float.self)
    var out = [Float](repeating: 0, count: n * 2)
    for i in 0..<n { out[2 * i] = l[i]; out[2 * i + 1] = r[i] }
    _ = out.withUnsafeBytes { write(1, $0.baseAddress!, $0.count) }
}
if err != 0 { fail("can't start capture", err) }
err = AudioDeviceStart(agg, proc)
if err != 0 { fail("can't start capture", err) }
dispatchMain()
