// Independent AppKit AX fixture. Build into MacAXFixture.app/Contents/MacOS/
// with: swiftc tests/native/Fixture.swift -o <bundle>/Contents/MacOS/MacAXFixture
// The bundle's Contents/Info.plist must include:
// CFBundleIdentifier=org.pymacauto.fixture, CFBundleExecutable=MacAXFixture,
// CFBundleName=MacAXFixture, CFBundlePackageType=APPL, LSUIElement=true.
// Start the fixture explicitly (the Python smoke only attaches), then grant
// Accessibility permission to the Python/terminal running that smoke.
// This fixture never requests app activation, focus or front ordering.

import AppKit

final class FixtureDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private var input: NSTextField!
    private var result: NSTextField!

    func applicationDidFinishLaunching(_ notification: Notification) {
        let content = NSView(frame: NSRect(x: 0, y: 0, width: 420, height: 170))
        content.setAccessibilityIdentifier("pymacauto.content")

        input = NSTextField(frame: NSRect(x: 24, y: 110, width: 260, height: 26))
        input.stringValue = "initial"
        input.setAccessibilityIdentifier("pymacauto.input")
        input.setAccessibilityLabel("Input")
        content.addSubview(input)
        let inputLabel = NSTextField(labelWithString: "Input")
        inputLabel.frame = NSRect(x: 2, y: 110, width: 20, height: 26)
        content.addSubview(inputLabel)

        let apply = NSButton(frame: NSRect(x: 300, y: 108, width: 96, height: 30))
        apply.title = "Apply"
        apply.bezelStyle = .rounded
        apply.setAccessibilityIdentifier("pymacauto.apply")
        apply.target = self
        apply.action = #selector(applyValue(_:))
        content.addSubview(apply)

        // NSTextField static text exposes its string as AXValue (not AXTitle).
        result = NSTextField(labelWithString: "not applied")
        result.frame = NSRect(x: 24, y: 52, width: 372, height: 26)
        result.setAccessibilityIdentifier("pymacauto.result")
        content.addSubview(result)

        window = NSWindow(
            contentRect: NSRect(x: 120, y: 120, width: 420, height: 170),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "MacAX Fixture"
        window.setAccessibilityIdentifier("pymacauto.window")
        window.isReleasedWhenClosed = false
        window.contentView = content
        window.orderBack(nil)
        let message = "pymacauto fixture ready pid=\(ProcessInfo.processInfo.processIdentifier) bundle=\(Bundle.main.bundleIdentifier ?? "missing")\n"
        FileHandle.standardOutput.write(Data(message.utf8))
    }

    @objc private func applyValue(_ sender: NSButton) {
        result.stringValue = "applied:\(input.stringValue)"
    }
}

let application = NSApplication.shared
_ = application.setActivationPolicy(.accessory)
let delegate = FixtureDelegate()
application.delegate = delegate
application.run()
