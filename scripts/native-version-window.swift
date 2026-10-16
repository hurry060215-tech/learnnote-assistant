// Read only the launched disposable application's on-screen windows.
import Foundation
import CoreGraphics
let pid = Int32(CommandLine.arguments[1])!
let rows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
let owned = rows.filter { ($0[kCGWindowOwnerPID as String] as? Int32) == pid && ($0[kCGWindowLayer as String] as? Int) == 0 }
let result = owned.map { row in ["id": row[kCGWindowNumber as String] ?? 0, "title": row[kCGWindowName as String] ?? "", "bounds": row[kCGWindowBounds as String] ?? [:]] }
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
