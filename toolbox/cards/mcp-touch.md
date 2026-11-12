# mcp-touch — tap, swipe, type and press keys on George's visible screen through the phone's MCP server

Every command on this card acts on George's visible screen at once. He sees it happen.
For a screen he does not see, use a hidden screen: `card screen`.
Read first with `card mcp-see`: node ids and coordinates come from android_get_screen_state and android_find_nodes.
Coordinates are screen pixels. The screen is 1080 x 2424.

System buttons and panels
  mcp android_press_back          mcp android_press_home          mcp android_press_recents
  mcp android_open_notifications  pulls the notification shade down
  mcp android_open_quick_settings opens the quick settings panel
  mcp android_press_key '{"key":"ENTER"}'                key: ENTER | BACK | DEL | HOME | TAB | SPACE

Touch by position
  mcp android_tap '{"x":540,"y":1200}'
  mcp android_double_tap '{"x":540,"y":1200}'
  mcp android_long_press '{"x":540,"y":1200,"duration":800}'                      duration in ms, optional
  mcp android_swipe '{"x1":540,"y1":1800,"x2":540,"y2":600,"duration":300}'
  mcp android_scroll '{"direction":"down","amount":"medium"}'                     direction: up down left right
  mcp android_pinch '{"center_x":540,"center_y":1200,"scale":1.5}'                above 1 zooms in, below 1 zooms out
  mcp android_custom_gesture '{"paths":[[{"x":100,"y":100,"time":0},{"x":400,"y":400,"time":300}]]}'
      Run `mcp tools android_custom_gesture` for the exact path format.

Touch by node (the node_id comes from the screen state)
  mcp android_click_node '{"node_id":"node_7faba97e"}'            the accessibility click
  mcp android_tap_node '{"node_id":"node_7faba97e"}'              a real tap inside the node's bounds
  mcp android_long_click_node '{"node_id":"node_7faba97e"}'
  mcp android_scroll_to_node '{"node_id":"node_7faba97e"}'        brings an off-screen node into view

Type into a text field (node_id of the field)
  mcp android_type_append_text '{"node_id":"node_1a2b3c4d","text":"hello"}'              types at the end
  mcp android_type_insert_text '{"node_id":"node_1a2b3c4d","text":"hello","offset":0}'   types at a position
  mcp android_type_replace_text '{"node_id":"node_1a2b3c4d","search":"old","new_text":"new"}'
  mcp android_type_clear_text '{"node_id":"node_1a2b3c4d"}'
  The text arrives key by key, like a keyboard.

Clipboard
  mcp android_set_clipboard '{"text":"copied words"}'             replaces what is on the clipboard

After an action
  mcp android_wait_for_idle '{"timeout":3000}'      then read the screen again to see what changed.

Known failure
  A node_id from an older screen state answers "Node not found": the screen changed. Read the screen again.
  Every tool exits 1 with the server's error text when it fails.
