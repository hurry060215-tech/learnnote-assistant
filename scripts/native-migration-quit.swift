// Request the existing Quit route only for the disposable process owned by the gate.
// This is not a window-close or cleanup guarantee; Python checks actual shutdown.
import AppKit
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(2)
}

let arguments = CommandLine.arguments
guard arguments.count == 3, let pid = Int32(arguments[1]), pid > 0,
      arguments[2].hasPrefix("/") else {
    fail("Expected an owned process ID and absolute executable path")
}
let expected = URL(fileURLWithPath: arguments[2]).resolvingSymlinksInPath().standardizedFileURL
guard let application = NSRunningApplication(processIdentifier: pid),
      application.processIdentifier == pid, !application.isTerminated,
      let executable = application.executableURL?.resolvingSymlinksInPath().standardizedFileURL,
      executable == expected else {
    fail("Running application does not match the owned executable")
}
let requested = application.terminate()
let proof: [String: Any] = [
    "pid": pid, "executable": executable.path, "quit_requested": requested,
]
let data = try JSONSerialization.data(withJSONObject: proof, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
if !requested {
    fail("Owned application rejected the existing native Quit request")
}
