// The values the mods hooks module keeps in the session's state.

// The three groups the pane lists mods under.
export type ModGroup = 'token savers' | 'chat tools' | 'display'

// What a mod's source shows it can do.
export type ModFeatures = {
  // Reads switches.json, so On/Off reaches it.
  hasSwitch: boolean
  // Draws a band above the prompt.
  hasBand: boolean
  // Draws a side pane.
  hasPane: boolean
  // Opens its pane again when the reopen marker appears.
  canReopen: boolean
}

// One row of the pane.
export type ModRow = {
  // The plugin.json name, which is also its key in switches.json.
  name: string
  title: string
  group: ModGroup
  tip: string
  // The folder it was found in, and any other folder holding a mod of the same name.
  path: string
  alsoAt: string[]
  features: ModFeatures
}

// One switch change from the pane. An absent field is left as it is.
export type SwitchChange = { isOff?: boolean; isHidden?: boolean }

declare module 'claude-code' {
  interface PluginState {
    mods: {
      rows: Shaped<ModRow[]>
      // The switches.json values, and whether the file could be read.
      switches: { isReadable: boolean; values: Record<string, boolean> }
      // A line for the bottom of the pane: what could not be read, or ''.
      note: string
      // This chat's session id, which a Reopen marker names; empty when there is none.
      chat: string
    }
  }
}
