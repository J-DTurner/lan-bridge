import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui

BarWidget {
  id: root
  moduleName: "lanbridge.sharing"
  readonly property string controller: Quickshell.env("HOME") + "/.local/bin/lan-bridge"
  property bool sharingOn: false
  property bool stateKnown: false
  property string stateTooltip: "Lan Bridge"
  readonly property bool busy: toggleProc.running
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function refresh() {
    if (!statusProc.running) statusProc.running = true
  }
  Component.onCompleted: refresh()
  Process {
    id: statusProc
    command: [root.controller, "bar-status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var data = JSON.parse(text)
          root.sharingOn = data.enabled === true
          root.stateTooltip = String(data.tooltip || "Lan Bridge")
          root.stateKnown = true
        } catch (error) {
          root.stateKnown = false
          root.stateTooltip = "Lan Bridge: status unavailable"
        }
      }
    }
  }
  Process {
    id: toggleProc
    command: [root.controller, "toggle", "--notify"]
    onExited: root.refresh()
  }
  Process {
    id: panelProc
    command: [root.controller, "panel"]
  }
  Timer { interval: 2000; repeat: true; running: true; onTriggered: root.refresh() }
  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.busy ? "⋯" : (root.sharingOn ? "󰌌" : "󰌐")
    active: root.sharingOn
    dimmed: !root.sharingOn && !root.busy
    interactive: root.stateKnown && !root.busy
    tooltipText: root.busy ? "Switching Lan Bridge…" : root.stateTooltip
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton && !root.busy) toggleProc.running = true
      if (mouseButton === Qt.RightButton && !panelProc.running) panelProc.running = true
    }
  }
}
