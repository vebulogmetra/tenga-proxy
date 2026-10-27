Country flags from [flag-icons](https://github.com/lipis/flag-icons), version 7.3.2,
MIT license (see LICENSE). Only two-letter 4:3 SVG assets are included.

Windows uses these images for leading regional-indicator emoji in profile and
group names, including the active profile in the status card. Names in storage
are preserved. Assets are local and require no network access at runtime.

The `win/` BMP variants are used by native Win32 tray menus and Windows GTK
name labels, so the installed app does not need SVG rendering for flags. Regenerate with
MSYS2 UCRT64 Python: `python tools/make_flag_bitmaps.py`.
