# mcp-apps — open apps, send intents, write files, use the camera and act on notifications through the MCP server

Reading tools are on `card mcp-see`. Touch tools are on `card mcp-touch`. Each command here changes something.

Apps
  mcp android_open_app '{"package_id":"com.google.android.gm"}'       This opens the app on George's visible screen.
  mcp android_close_app '{"package_id":"com.spotify.music"}'          Kills a background app's process.
  mcp android_open_uri '{"uri":"https://example.com"}'                Opens a link, tel:, mailto:, geo: or an app link
                                                                      on George's visible screen.
  mcp android_open_uri '{"uri":"tel:+14155551234"}'                   Opens the dialer with the number filled in.
  mcp android_send_intent '{"type":"activity","action":"android.settings.BLUETOOTH_SETTINGS"}'
      type: activity | broadcast | service. Optional: data, component, extras, extras_types, flags.
      This starts that screen, broadcast or service at once. `mcp tools android_send_intent` has the full form.

Files (location_id comes from android_list_storage_locations)
  mcp android_write_file '{"location_id":"LOCATION","path":"notes/a.txt","content":"text"}'        creates or replaces
  mcp android_append_file '{"location_id":"LOCATION","path":"notes/a.txt","content":"more"}'
  mcp android_file_replace '{"location_id":"LOCATION","path":"notes/a.txt","old_string":"a","new_string":"b"}'
  mcp android_download_from_url '{"location_id":"LOCATION","path":"file.pdf","url":"https://example.com/file.pdf"}'
  mcp android_delete_file '{"location_id":"LOCATION","path":"notes/a.txt"}'                        deletes one file
  Checked 2026-11-11: the three built-in locations are read-only ("allow_write": false). A writable location
  must be added by George inside the MCP app. For ordinary files use `card files`.

Camera
  mcp android_take_camera_photo '{"camera_id":"0","quality":80}'          takes a photo; the answer is the picture
  mcp android_save_camera_photo '{"camera_id":"0","location_id":"LOCATION","path":"photo.jpg"}'
  mcp android_save_camera_video '{"camera_id":"0","location_id":"LOCATION","path":"clip.mp4","duration":10}'
      duration in seconds, 30 at most; it records sound unless "audio":false.
  camera_id 0 is the back camera and 1 is the front camera.

Notifications (ids come from android_notification_list)
  mcp android_notification_open '{"notification_id":"d439db75"}'          opens it on George's visible screen
  mcp android_notification_dismiss '{"notification_id":"d439db75"}'       removes it
  mcp android_notification_snooze '{"notification_id":"d439db75","duration_ms":600000}'
  mcp android_notification_action '{"action_id":"f8ea555b"}'              presses that notification's button
  mcp android_notification_reply '{"action_id":"f8ea555b","text":"On my way"}'
      This sends a real reply in that app at once. It works on actions whose accepts_text is true.

Known failure (checked 2026-11-11)
  The three camera tools answer "CAMERA permission not granted". The grant command is on `card mcp-see`.
  Writes answer an error while no writable storage location exists.
