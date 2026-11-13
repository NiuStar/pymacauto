import AppKit

final class PerformanceDelegate: NSObject, NSApplicationDelegate, NSTableViewDataSource, NSTableViewDelegate {
    var window: NSWindow!
    var table: NSTableView!
    var page = "A"
    func applicationDidFinishLaunching(_ notification: Notification) {
        let content = NSView(frame: NSRect(x: 0, y: 0, width: 600, height: 420))
        for (i, name) in ["A", "B"].enumerated() {
            let button = NSButton(frame: NSRect(x: 20 + i * 100, y: 380, width: 90, height: 26))
            button.title = name
            button.setAccessibilityIdentifier("page." + name)
            button.target = self
            button.action = #selector(changePage(_:))
            content.addSubview(button)
        }
        table = NSTableView(frame: NSRect(x: 0, y: 0, width: 560, height: 340))
        for i in 0..<5 {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("c\(i)"))
            column.title = "Field\(i)"
            column.width = 105
            table.addTableColumn(column)
        }
        table.setAccessibilityIdentifier("grid.A")
        table.dataSource = self
        table.delegate = self
        let scroll = NSScrollView(frame: NSRect(x: 20, y: 20, width: 560, height: 340))
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        content.addSubview(scroll)
        window = NSWindow(contentRect: NSRect(x: 100, y: 100, width: 600, height: 420), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "MacAX Performance Fixture"
        window.setAccessibilityIdentifier("perf.window")
        window.isReleasedWhenClosed = false
        window.contentView = content
        window.orderBack(nil)
    }
    func numberOfRows(in tableView: NSTableView) -> Int { return 100 }
    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        let label = NSTextField(labelWithString: "\(page):\(row):\(tableColumn!.identifier.rawValue)")
        return label
    }
    @objc func changePage(_ sender: NSButton) {
        page = sender.title
        table.setAccessibilityIdentifier("grid." + page)
        table.reloadData()
    }
}
let app = NSApplication.shared
_ = app.setActivationPolicy(.accessory)
let delegate = PerformanceDelegate()
app.delegate = delegate
app.run()
