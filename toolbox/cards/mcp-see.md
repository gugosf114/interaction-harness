# mcp-see — read George's visible screen, apps, files and notifications through the phone's MCP server

The server is an app on the phone (port 8080). One command reaches all 55 of its tools:
  mcp TOOL 'JSON ARGUMENTS'      call one tool          mcp tools            list every tool with its arguments
  mcp tools TOOL                 one tool's full description
The first line of every answer is the server's own caution note. The data starts on line two.
It sees George's visible screen only. A hidden screen is invisible to it: use `card screen` for those.
The 16 tools here only read. The tools that act are on `card mcp-touch` and `card mcp-apps`.

The screen
  mcp android_get_screen_state                                   app, size, and one line per node: node_id, class, text,
                                                                 desc, res_id, bounds (left,top,right,bottom), flags
  mcp android_get_screen_state '{"include_screenshot":true}'     the same, plus a picture
  mcp android_find_nodes '{"by":"text","value":"Send"}'          by: text | content_desc | resource_id | class_name
  mcp android_find_nodes '{"by":"text","value":"Net","exact_match":false}'
      -> {"nodes":[{"node_id":"node_7faba97e","text":...,"bounds":{"left":434,"top":2303,"right":644,"bottom":2419},...}]}
  mcp android_get_node_details '{"node_ids":["node_7faba97e"]}'   full text of nodes whose text was cut at 100 characters
  mcp android_wait_for_node '{"by":"text","value":"Done","timeout":5000}'    waits up to 5 s; "found":true or false
  mcp android_wait_for_idle '{"timeout":3000}'                    waits until the screen stops changing

Notifications, clipboard, logs, place
  mcp android_notification_list '{"limit":5}'                     newest first: notification_id, app_name, title, text,
                                                                 timestamp, actions[] with action_id and accepts_text
  mcp android_notification_list '{"package_name":"com.whatsapp","limit":10}'
  mcp android_get_clipboard
  mcp android_get_device_logs '{"last_lines":50,"level":"E","package_name":"com.termux"}'    level: V D I W E F
  mcp android_get_location '{"fresh_fix":false}'                  latitude, longitude, accuracy, street address

Apps and files
  mcp android_list_apps '{"filter":"user","name_query":"chrome"}'     filter: all | user | system
  mcp android_list_storage_locations                              ids such as builtin:downloads, with read and write flags
  mcp android_list_files '{"location_id":"builtin:downloads","path":"","limit":50}'
  mcp android_read_file '{"location_id":"builtin:downloads","path":"notes.txt","offset":0,"limit":200}'
      The built-in locations show only files this app made itself. Other files: use `card files`.

Cameras
  mcp android_list_cameras                                       -> camera 0 back, camera 1 front
  mcp android_list_camera_photo_resolutions '{"camera_id":"0"}'
  mcp android_list_camera_video_resolutions '{"camera_id":"0"}'

Known failure (checked 2026-11-19)
  Camera and location work since 2026-11-19, when the MCP app was given those permissions. If a tool answers
  "CAMERA permission not granted" or "Location permission not granted" again, the grant command is:
  adb -s 127.0.0.1:5555 shell pm grant com.danielealbano.androidremotecontrolmcp.debug android.permission.CAMERA
  (the same with android.permission.ACCESS_FINE_LOCATION)
  "the phone MCP server did not answer": run `deb phone-link`, which reopens the door.
