import AppKit
import CoreGraphics

let bundleID = "com.t3tools.t3code"
let appURL = URL(fileURLWithPath: "/Applications/T3 Code (Alpha).app")
let workspace = NSWorkspace.shared
var launching = false

func log(_ message: String) {
    FileHandle.standardError.write(Data("\(Date()): \(message)\n".utf8))
}

// Only hide launches initiated here; opening T3 from the Dock stays visible.
func hideOnceVisible(_ app: NSRunningApplication) {
    var hideRequested = false
    Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { timer in
        if app.isTerminated {
            timer.invalidate()
            return
        }
        if hideRequested {
            log(app.isHidden
                ? "T3 is hidden (PID \(app.processIdentifier))"
                : "T3 is visible after the hide request; leaving its window alone")
            timer.invalidate()
            return
        }
        guard let windows = CGWindowListCopyWindowInfo(
            [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID
        ) as? [[String: Any]] else {
            log("Cannot read window metadata")
            exit(1)
        }
        let visible = windows.contains {
            ($0[kCGWindowOwnerPID as String] as? Int32) == app.processIdentifier
                && ($0[kCGWindowLayer as String] as? Int) == 0
        }
        if visible {
            // Observe the result on the next tick: hiding is asynchronous.
            _ = app.hide()
            hideRequested = true
        }
    }
}

let timer = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { _ in
    guard !launching,
          NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).isEmpty
    else { return }

    launching = true
    let configuration = NSWorkspace.OpenConfiguration()
    configuration.activates = false
    workspace.openApplication(at: appURL, configuration: configuration) { app, error in
        DispatchQueue.main.async {
            guard let app else {
                log("Cannot launch T3: \(error!.localizedDescription)")
                exit(1)
            }
            launching = false
            log("Launched T3 (PID \(app.processIdentifier)); waiting to hide its window")
            hideOnceVisible(app)
        }
    }
}

log("Watching T3; existing windows remain unchanged")
timer.fire()
RunLoop.main.run()
