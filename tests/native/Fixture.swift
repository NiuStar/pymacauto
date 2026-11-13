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
        let content = NSView(frame: NSRect(x: 0, y: 0, width: 640, height: 170))
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
        let modal = NSButton(frame: NSRect(x: 300, y: 8, width: 96, height: 30))
        modal.title = "Sheet"
        modal.setAccessibilityIdentifier("pymacauto.sheet")
        modal.target = self
        modal.action = #selector(openSheet(_:))
        content.addSubview(modal)
        let check = NSButton(checkboxWithTitle: "Enabled", target: nil, action: nil)
        check.frame = NSRect(x: 24, y: 8, width: 85, height: 26)
        check.setAccessibilityIdentifier("pymacauto.check")
        content.addSubview(check)
        let slider = NSSlider(value: 2, minValue: 0, maxValue: 10, target: nil, action: nil)
        slider.frame = NSRect(x: 112, y: 8, width: 80, height: 26)
        slider.setAccessibilityIdentifier("pymacauto.slider")
        content.addSubview(slider)
        let popup = NSPopUpButton(frame: NSRect(x: 198, y: 8, width: 90, height: 26), pullsDown: false)
        popup.addItems(withTitles: ["One", "Two"])
        popup.setAccessibilityIdentifier("pymacauto.popup")
        content.addSubview(popup)
        let delayed = NSButton(frame: NSRect(x: 300, y: 40, width: 96, height: 26))
        delayed.title = "Delayed"
        delayed.setAccessibilityIdentifier("pymacauto.delayed")
        delayed.target = self
        delayed.action = #selector(delayedValue(_:))
        content.addSubview(delayed)
        let radio = NSButton(radioButtonWithTitle: "Choice", target: nil, action: nil)
        radio.frame = NSRect(x: 24, y: 80, width: 85, height: 24)
        radio.setAccessibilityIdentifier("pymacauto.radio")
        content.addSubview(radio)
        let tabs = NSTabView(frame: NSRect(x: 430, y: 10, width: 195, height: 145))
        tabs.setAccessibilityIdentifier("pymacauto.tabs")
        for name in ["First", "Second"] {
            let item = NSTabViewItem(identifier: name)
            item.label = name
            item.view = NSView(frame: .zero)
            tabs.addTabViewItem(item)
        }
        content.addSubview(tabs)

        // NSTextField static text exposes its string as AXValue (not AXTitle).
        result = NSTextField(labelWithString: "not applied")
        result.frame = NSRect(x: 24, y: 52, width: 372, height: 26)
        result.setAccessibilityIdentifier("pymacauto.result")
        content.addSubview(result)

        window = NSWindow(
            contentRect: NSRect(x: 120, y: 120, width: 640, height: 170),
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

    @objc private func delayedValue(_ sender: NSButton) {
        result.stringValue = "waiting"
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
            self.result.stringValue = "delayed ready"
            NSAccessibility.post(element: self.result!, notification: .valueChanged)
        }
    }

    @objc private func openSheet(_ sender: NSButton) {
        let sheet = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 220, height: 90),
                             styleMask: [.titled], backing: .buffered, defer: false)
        sheet.setAccessibilityIdentifier("pymacauto.modal")
        window.beginSheet(sheet, completionHandler: nil)
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
