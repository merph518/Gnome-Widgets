-- Cairo drawing for the speech widget, fed by speechqueue.py:
--   draw.txt      geometry (logical px, from the card's top left); its scale line is the
--                 display's scale and the text scale, its shadow line the margin round the card
--   widget.txt    conky's markup (the header and the Sessions label), shown through conky_widget
--   sessions.txt  the sessions list, a line per session, reread when draw.txt names a new version
--   list-scroll   how many rows conky-mouse.py has scrolled the list down; 0 until it has
--   volume-preview  the volume under the pointer while conky-mouse.py drags the volume slider
--   voice-menu    present while conky-mouse.py has the voice list open: the first voice shown and the
--                 one under the pointer (-1 for none), as "<scroll> <hover>"
--   close-confirm present while conky-mouse.py has the close prompt open: the button under the
--                 pointer (0 none, 1 OK, 2 Cancel) and whether the session is busy, then its name
-- and, read only, the Spotify widget's bg.txt (or the file ~/.config/conky-widgets/speech/
-- background names), whose colour the card fades to with it. Everything drawn is the
-- foreground or a share of it, as the Spotify widget's controls are, so the widget follows
-- its background.
require 'cairo'
pcall(require, 'cairo_xlib')

-- The shared drawing helpers sit in ../common, installed or in a checkout.
local here = debug.getinfo(1, 'S').source:match('^@(.*)/[^/]*$')
    or (os.getenv('CSN_DIR') or '/usr/share/conky-widgets') .. '/speech'
package.path = here .. '/../common/?.lua;' .. package.path
local theme = require 'theme'
local set, rounded_rect = theme.set, theme.rounded_rect

local cache = os.getenv('HOME') .. '/.cache/conky-widgets/speech/'
local BG_SETTING = os.getenv('HOME') .. '/.config/conky-widgets/speech/background'
local BG_FILE = os.getenv('HOME') .. '/.cache/conky-spotify-nowplaying/bg.txt'
local FONT = 'Ubuntu Sans'
local hover_x, hover_y = -1, -1           -- window px
local margin = 0                          -- the shadow margin around the card, in window px
local frame = nil                         -- draw.txt as the background hook read it this frame
local bg = {0.094, 0.094, 0.094}          -- current (fading) colour; starts at Spotify's #181818
local fg, fg_back = theme.LIGHT, theme.DARK   -- fg_back: drawn on fg, like the pause icon
local clock = {stamp = nil, pos = 0, running = false}
local sessions = {version = nil, rows = {}}
local scroll = nil                        -- eased list scroll position, in rows

local function read(name)
    local f = io.open(cache .. name)
    if not f then return nil end
    local s = f:read('*a')
    f:close()
    return s
end

local function load_draw()
    -- {key = {numbers...}}, and each line's own text in d.text[key] for the ones that end in a
    -- label ("Voice: amy"); d.items is the voice list's lines, each {current, label}
    local d = {text = {}, items = {}}
    for line in (read('draw.txt') or ''):gmatch('[^\n]+') do
        local key, rest = line:match('^(%S+)%s+(.*)$')
        if key == 'item' then
            local current, label = rest:match('^(%d)%s+(.*)$')
            d.items[#d.items + 1] = {current = current == '1', label = label or ''}
        elseif key then
            local t = {}
            for v in rest:gmatch('%S+') do t[#t + 1] = tonumber(v) or v end
            d[key], d.text[key] = t, rest
        end
    end
    return d
end

local function label_after(rest, n)
    -- the text after the first n fields of a draw.txt line
    for _ = 1, n do rest = rest:gsub('^%S+%s*', '', 1) end
    return rest
end

local function load_sessions(version)
    -- sessions.txt's lines (speechqueue.py's session_line) as {speech, speaking, queued,
    -- flags, name, repo, last, pill, chips, span}, each chip {line, x, width, text}
    if version == sessions.version then return end
    local rows = {}
    for line in (read('sessions.txt') or ''):gmatch('[^\n]+') do
        local f = {}
        for v in (line .. '\t'):gmatch('([^\t]*)\t') do f[#f + 1] = v end
        rows[#rows + 1] = {speech = f[2], speaking = f[3] == '1', queued = tonumber(f[4]) or 0,
                           flags = (f[5] or '-') ~= '-' and f[5]:gsub(',', ' ') or '',
                           name = f[6] or '', repo = f[7] or '',
                           last = f[8] or '', pill = f[9] or '', chips = {},
                           span = tonumber(f[11]) or 1}
        for tok in (f[10] or ''):gmatch('%S+') do
            local line, x, w, str = tok:match('^(%d+):([%d.]+):([%d.]+):(.+)$')
            if line then
                local chips = rows[#rows].chips
                chips[#chips + 1] = {line = tonumber(line), x = tonumber(x), w = tonumber(w), text = str}
            end
        end
    end
    sessions = {version = version, rows = rows}
end

function conky_mouse(event)
    if event.type == 'mouse_move' or event.type == 'mouse_enter' then
        hover_x, hover_y = event.x, event.y
    elseif event.type == 'mouse_leave' then
        hover_x, hover_y = -1, -1
    end
    return false
end

local function with_cairo(fn)
    local cs = cairo_xlib_surface_create(conky_window.display, conky_window.drawable,
                                         conky_window.visual, conky_window.width, conky_window.height)
    local cr = cairo_create(cs)
    fn(cr)
    cairo_destroy(cr)
    cairo_surface_destroy(cs)
end

local function dt()
    return (conky_info and conky_info.update_interval) or 0.05
end

local function secondary() return theme.secondary(fg, bg) end

local function bg_file()
    -- the background setting's path, its first line, else the Spotify widget's bg.txt
    local f = io.open(BG_SETTING)
    local path = f and (f:read('*l') or ''):match('^%s*(.-)%s*$') or ''
    if f then f:close() end
    if path == '' then return BG_FILE end
    return (path:gsub('^~/', os.getenv('HOME') .. '/'))
end

function conky_widget()
    -- conky.text: speechqueue.py's markup. Conky reads it before the draw hooks run, so the
    -- fade is worked out here, as the Spotify widget's is, and the markup's colours and everything
    -- the hooks draw share one foreground in every frame.
    fg, fg_back = theme.fade(bg, bg_file())
    return read('widget.txt') or ''
end

function conky_fg(which)
    -- ${lua_parse fg title} and ${lua_parse fg text} in speechqueue.py's markup
    return theme.conky_colour(which == 'title' and fg or secondary())
end

function conky_draw_background()
    -- the card, inset by the shadow margin draw.txt gives, and its shadow in that margin
    if conky_window == nil then return end
    local d = load_draw()
    frame = d
    local s = d.scale and d.scale[1] or 1
    margin = (d.shadow and d.shadow[1] or 0) * s
    local w, h = conky_window.width - 2 * margin, conky_window.height - 2 * margin
    if w <= 0 or h <= 0 then margin, w, h = 0, conky_window.width, conky_window.height end
    local rad = math.min(24, h / 4)
    with_cairo(function(cr)
        if margin > 0 then theme.draw_shadow(cr, margin, margin, w, h, rad, s) end
        rounded_rect(cr, margin, margin, w, h, rad)
        cairo_set_source_rgb(cr, bg[1], bg[2], bg[3])
        cairo_fill(cr)
    end)
end

-- Shapes and text ------------------------------------------------------------------------

local function rounded_line(cr, x0, y0, x1, y1, width)
    cairo_set_line_width(cr, width)
    cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND)
    cairo_move_to(cr, x0, y0)
    cairo_line_to(cr, x1, y1)
    cairo_stroke(cr)
end

local function triangle(cr, cx, cy, h, dir)
    -- right-pointing (dir = 1) or left-pointing (dir = -1) triangle with softened corners
    cairo_set_line_join(cr, CAIRO_LINE_JOIN_ROUND)
    cairo_set_line_width(cr, h * 0.25)
    cairo_move_to(cr, cx - dir * h * 0.75, cy - h)
    cairo_line_to(cr, cx + dir * h * 0.85, cy)
    cairo_line_to(cr, cx - dir * h * 0.75, cy + h)
    cairo_close_path(cr)
    cairo_fill_preserve(cr)
    cairo_stroke(cr)
end

local function hovered(x0, y0, x1, y1)
    -- whether the pointer is over the box, given from the card's top left like draw.txt
    local x, y = hover_x - margin, hover_y - margin
    return hover_x >= 0 and x >= x0 and x <= x1 and y >= y0 and y <= y1
end

local function shade(cr, cx, cy, half)
    -- a control in the foreground, full while the pointer is over it
    set(cr, fg, hovered(cx - half, cy - half, cx + half, cy + half) and 1 or 0.7)
end

local face = ''                           -- the font font() last set, which fit's cache keys on

local function font(cr, pt, text, s, bold)
    cairo_select_font_face(cr, FONT, CAIRO_FONT_SLANT_NORMAL,
                           bold and CAIRO_FONT_WEIGHT_BOLD or CAIRO_FONT_WEIGHT_NORMAL)
    cairo_set_font_size(cr, pt * text * 96 / 72 * s)
    face = (bold and 'b' or '') .. pt * text * s
end

local ext = cairo_text_extents_t:create()
local fext = cairo_font_extents_t:create()

local function width_of(cr, str)
    cairo_text_extents(cr, str, ext)
    return ext.x_advance
end

local fitted, fitted_count = {}, 0        -- fit's answers, as the same rows ask every frame

local function fit(cr, str, width)
    -- str, cut with an ellipsis to the longest start that fits in width, found by halving
    -- (a last line can run to a thousand characters) and kept, since the list asks again
    -- each frame
    local key = face .. '\0' .. width .. '\0' .. str
    if fitted[key] then return fitted[key] end
    local out = str
    if width_of(cr, str) > width then
        local chars = {}
        for _, c in utf8.codes(str) do chars[#chars + 1] = utf8.char(c) end
        local function cut(n) return table.concat(chars, '', 1, n):gsub('%s+$', '') .. '…' end
        local lo, hi = 0, #chars - 1               -- the longest start that fits is lo or above
        while lo < hi do
            local mid = (lo + hi + 1) // 2
            if width_of(cr, cut(mid)) <= width then lo = mid else hi = mid - 1 end
        end
        out = (lo > 0 or width_of(cr, cut(0)) <= width) and cut(lo) or ''
    end
    if fitted_count >= 64 then fitted, fitted_count = {}, 0 end
    fitted[key], fitted_count = out, fitted_count + 1
    return out
end

local function show(cr, str, x, cy, align)
    -- str with its line centred on cy, from x (align 'left'), to x ('right'), or round x
    -- ('centre'); returns its width
    cairo_font_extents(cr, fext)
    local w = width_of(cr, str)
    local left = align == 'right' and x - w or align == 'centre' and x - w / 2 or x
    cairo_move_to(cr, left, cy + (fext.ascent - fext.descent) / 2)
    cairo_show_text(cr, str)
    return w
end

-- The parts of the card --------------------------------------------------------------------

local function draw_window_buttons(cr, w, s)
    -- minimize (a bar) and close (a cross), as the Spotify widget's
    local min_cx, close_cx, cy, h = w[1] * s, w[2] * s, w[3] * s, w[4] * s / 2
    local half = (w[2] - w[1]) * s / 2
    shade(cr, min_cx, cy, half)
    rounded_line(cr, min_cx - h, cy, min_cx + h, cy, 2 * s)
    shade(cr, close_cx, cy, half)
    cairo_move_to(cr, close_cx - h, cy - h)
    cairo_line_to(cr, close_cx + h, cy + h)
    rounded_line(cr, close_cx - h, cy + h, close_cx + h, cy - h, 2 * s)
end

local function draw_speaker(cr, h, s, state)
    -- the speaker left of the header: two sound waves while a clip plays, none while paused,
    -- and the text's colour while idle
    local cx, cy, u = h[1] * s, h[2] * s, s
    set(cr, state == 'idle' and secondary() or fg)
    cairo_move_to(cr, cx - 9 * u, cy - 3 * u)
    cairo_line_to(cr, cx - 5 * u, cy - 3 * u)
    cairo_line_to(cr, cx, cy - 7 * u)
    cairo_line_to(cr, cx, cy + 7 * u)
    cairo_line_to(cr, cx - 5 * u, cy + 3 * u)
    cairo_line_to(cr, cx - 9 * u, cy + 3 * u)
    cairo_close_path(cr)
    cairo_fill(cr)
    if state ~= 'playing' then return end
    cairo_set_line_width(cr, 1.6 * u)
    cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND)
    for _, r in ipairs({4, 8}) do
        cairo_new_sub_path(cr)
        cairo_arc(cr, cx + 1 * u, cy, r * u, -math.pi / 4, math.pi / 4)
        cairo_stroke(cr)
    end
end

local function round_button(cr, cx, cy, size, active)
    -- a footer button as the pause button is drawn: the foreground's circle, a little bigger
    -- under the pointer; dimmed, with its icon in the foreground, while there is nothing to skip.
    -- Leaves the icon's colour set.
    local on = active and hovered(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)
    set(cr, fg, active and 1 or 0.28)
    cairo_new_path(cr)
    cairo_arc(cr, cx, cy, size / 2 * (on and 1.06 or 1), 0, 2 * math.pi)
    cairo_fill(cr)
    if active then cairo_set_source_rgb(cr, bg[1], bg[2], bg[3]) else set(cr, fg, 0.6) end
end

local function draw_skip_buttons(cr, b, s)
    -- skip (this line: a triangle at a bar) and next (on to the next session: two triangles),
    -- round buttons after the pause button
    local skip_cx, next_cx, cy, size, active = b[1] * s, b[2] * s, b[3] * s, b[4] * s, b[5] == 1
    round_button(cr, skip_cx, cy, size, active)
    triangle(cr, skip_cx - size * 0.06, cy, size * 0.15, 1)
    rounded_line(cr, skip_cx + size * 0.2, cy - size * 0.15, skip_cx + size * 0.2, cy + size * 0.15, size * 0.086)
    round_button(cr, next_cx, cy, size, active)
    triangle(cr, next_cx - size * 0.12, cy, size * 0.139, 1)
    triangle(cr, next_cx + size * 0.13, cy, size * 0.139, 1)
end

local function fmt_time(sec)
    sec = math.floor(math.max(sec, 0))
    return string.format('%d:%02d', sec // 60, sec % 60)
end

local function draw_progress(cr, p, s, text, pos)
    -- elapsed at the left, the clip's length at the right, the bar between them, as the
    -- Spotify widget's seek bar and times (without the knob: a clip can't be sought)
    local x0, x1, y, duration = p[1] * s, p[2] * s, p[3] * s, p[6]
    pos = math.min(math.max(pos, 0), duration)
    font(cr, 9, text, s)
    set(cr, secondary())
    local total = fmt_time(duration)
    local tw = width_of(cr, total)
    show(cr, fmt_time(pos), x0, y, 'left')
    show(cr, total, x1, y, 'right')
    local b0, b1 = x0 + tw + 10 * s, x1 - tw - 10 * s
    local fx = b0 + (b1 - b0) * (duration > 0 and pos / duration or 0)
    set(cr, fg, 0.3)
    rounded_line(cr, b0, y, b1, y, 4 * s)
    set(cr, fg)
    if fx > b0 then rounded_line(cr, b0, y, fx, y, 4 * s) end
end

local function list_offset(last)
    local offset = tonumber((read('list-scroll') or ''):match('^%s*(%S+)') or '') or 0
    return math.min(math.max(offset, 0), last)
end

local function draw_scrollbar(cr, x, top, height, s, rows, count, at, last)
    -- a slim bar in the card's right margin: the track, and a thumb as long as the share of
    -- the sessions that shows
    local w = 4 * s
    local y0, y1 = top + w / 2, top + height - w / 2
    local len = (y1 - y0) * math.min(rows / count, 1)
    local ty = y0 + (y1 - y0 - len) * math.min(math.max(at / last, 0), 1)
    set(cr, fg, 0.3)
    rounded_line(cr, x, y0, x, y1, w)
    set(cr, fg)
    rounded_line(cr, x, ty, x, ty + len, w)
end

local SEGMENTS = {{'on', 'On'}, {'alerts', 'Alerts'}, {'off', 'Off'}}

local function draw_control(cr, xs, cy, seg_h, s, text, speech)
    -- On | Alerts | Off: a track of the foreground's tint, the current setting a pill of the
    -- foreground with its label in fg_back, the others in the text's colour
    local h = seg_h * s
    local x0, x3 = xs[1] * s, xs[4] * s
    set(cr, fg, hovered(x0, cy - h / 2, x3, cy + h / 2) and 0.2 or 0.12)
    rounded_rect(cr, x0, cy - h / 2, x3 - x0, h, h / 2)
    cairo_fill(cr)
    font(cr, 9, text, s, true)
    for i, seg in ipairs(SEGMENTS) do
        local a, b = xs[i] * s, xs[i + 1] * s
        if seg[1] == speech then
            set(cr, fg)
            rounded_rect(cr, a, cy - h / 2, b - a, h, h / 2)
            cairo_fill(cr)
            set(cr, fg_back)
        else
            set(cr, secondary())
        end
        show(cr, seg[2], (a + b) / 2, cy, 'centre')
    end
end

local function draw_block(cr, r, x0, y, row, b, s, text)
    -- the repository's name on the row's first line, cut to the block's width, and under it the
    -- issue numbers, wrapped as speechqueue.py laid them (b is its block line); a click on one
    -- opens that issue. A number is plain text on the card, with no border or background and
    -- nothing right of it, lit while its session is speaking and underlined under the pointer.
    -- A rule at the block's left runs the whole height: a thin dim one, or while its session is
    -- speaking a thicker, lit one
    if r.repo == '' then return end
    local rule, pad, tw = b[1] * s, b[2] * s, b[3] * s
    local chips_top, pitch, chip_h = b[4] * s, b[5] * s, b[6] * s
    local cy = y + row / 2
    font(cr, 9, text, s, true)
    cairo_font_extents(cr, fext)
    local top, bottom = cy - fext.height / 2, cy + fext.height / 2
    if #r.chips > 0 then bottom = y + chips_top + (r.chips[#r.chips].line + 1) * pitch end
    local thick = r.speaking and rule * 2 or rule
    set(cr, fg, r.speaking and 1 or 0.35)
    cairo_rectangle(cr, x0, top, thick, bottom - top)
    cairo_fill(cr)
    local tx = x0 + rule + pad
    set(cr, fg)
    show(cr, fit(cr, r.repo, tw), tx, cy, 'left')
    font(cr, 9, text, s)
    for _, c in ipairs(r.chips) do
        local cx, ccy, w = tx + c.x * s, y + chips_top + c.line * pitch + pitch / 2, c.w * s
        if hovered(cx, ccy - chip_h / 2, cx + w, ccy + chip_h / 2) then
            set(cr, fg, 0.6)
            cairo_set_line_width(cr, 1 * s)
            cairo_move_to(cr, cx + w - width_of(cr, c.text), ccy + chip_h * 0.38)
            cairo_line_to(cr, cx + w, ccy + chip_h * 0.38)
            cairo_stroke(cr)
        end
        if r.speaking then set(cr, fg) else set(cr, secondary()) end
        show(cr, c.text, cx + w, ccy, 'right')
    end
end

local function draw_pill(cr, str, x, cy, w, h, s, text, on)
    -- the pill after a session's name, naming the ready pull requests a click on it opens: the
    -- foreground with its text in fg_back, a little bigger under the pointer
    set(cr, fg)
    local grow = on and 1.5 * s or 0
    rounded_rect(cr, x - grow, cy - h / 2 - grow, w + 2 * grow, h + 2 * grow, h / 2 + grow)
    cairo_fill(cr)
    font(cr, 9, text, s)
    set(cr, fg_back)
    show(cr, str, x + w / 2, cy, 'centre')
end

local function draw_row(cr, r, x0, y, row, c, s, text, blk)
    -- a session's row: its repository's name and issue numbers, its name (a click on it asks to
    -- close the session) and the pill naming the pull requests a click on the pill opens,
    -- busy / idle / waiting / bg / question, how many lines it has queued and its setting;
    -- with speech on, a second row of its last line read aloud. The name is underlined and the
    -- pill grows under the pointer. Returns how many rows it took.
    local cy = y + row / 2
    draw_control(cr, c, cy, c[5], s, text, r.speech)
    local right = c[6] * s
    font(cr, 9, text, s)
    set(cr, secondary())
    if r.queued > 0 then right = right - show(cr, r.queued .. ' queued', right, cy, 'right') - 10 * s end
    local flags_w = r.flags ~= '' and width_of(cr, r.flags) + 8 * s or 0
    local pill_w = r.pill ~= '' and width_of(cr, r.pill) + 12 * s or 0
    local box_w = (blk[1] + blk[2] + blk[3]) * s
    draw_block(cr, r, x0, y, row, blk, s, text)
    local name_x = x0 + box_w + 8 * s
    font(cr, 11, text, s)
    local name = fit(cr, r.name, right - name_x - flags_w - (pill_w > 0 and pill_w + 8 * s or 0))
    local nw = width_of(cr, name)
    local after = name_x + nw
    if hovered(name_x - 4 * s, cy - row / 2, after + 4 * s, cy + row / 2) then
        set(cr, fg, 0.6)
        cairo_set_line_width(cr, 1 * s)
        cairo_move_to(cr, name_x, cy + row * 0.32)
        cairo_line_to(cr, after, cy + row * 0.32)
        cairo_stroke(cr)
    end
    if pill_w > 0 then
        local x1 = after + 8 * s + pill_w
        local on = hovered(after + 4 * s, cy - row / 2, x1 + 4 * s, cy + row / 2)
        draw_pill(cr, r.pill, after + 8 * s, cy, pill_w, c[5] * s * 0.85, s, text, on)
        after = x1
        font(cr, 11, text, s)
    end
    set(cr, fg)
    show(cr, name, name_x, cy, 'left')
    if flags_w > 0 then
        font(cr, 9, text, s)
        set(cr, secondary())
        show(cr, r.flags, after + 8 * s, cy, 'left')
    end
    if r.speech ~= 'on' then return r.span end
    font(cr, 11, text, s)
    set(cr, secondary(), 0.65)                     -- a lighter grey than the name and tags
    show(cr, fit(cr, r.last, c[1] * s - 10 * s - name_x), name_x, cy + row, 'left')   -- clear of the setting
    return r.span
end

local function draw_list(cr, l, version, c, blk, s, text)
    local x0, x1, top, row, height = l[1] * s, l[2] * s, l[3] * s, l[4] * s, l[5] * s
    local last = l[8]
    load_sessions(version)
    local rows = sessions.rows
    if #rows == 0 then
        font(cr, 11, text, s)
        set(cr, secondary())
        show(cr, 'No Claude sessions open', x0, top + row / 2, 'left')
        scroll = nil
        return
    end
    local target = list_offset(last)
    if scroll == nil then scroll = target end
    scroll = scroll + (target - scroll) * (1 - math.exp(-dt() * 12 / 1.1))   -- ~0.33 s glide
    if last > 0 then
        local total = 0                            -- in rows: a session takes as many as its block needs
        for _, r in ipairs(rows) do total = total + r.span end
        draw_scrollbar(cr, x1 + 8 * s, top, height, s, height / row, total, scroll, last)
    end
    cairo_save(cr)
    cairo_rectangle(cr, x0, top, x1 - x0, height)
    cairo_clip(cr)
    local at = 0
    for _, r in ipairs(rows) do
        local y = top + (at - scroll) * row
        if y > top + height then break end
        at = at + draw_row(cr, r, x0, y, row, c, s, text, blk)
    end
    cairo_restore(cr)
end

local function draw_footer(cr, f, s)
    -- pause (two bars) while speech plays, resume (a triangle) while it is paused: the
    -- foreground's circle with the icon in the card's colour, a little bigger under the pointer
    local cx, cy, size, paused = f[1] * s, f[2] * s, f[3] * s, f[4] == 1
    local on = hovered(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)
    set(cr, fg)
    cairo_new_path(cr)
    cairo_arc(cr, cx, cy, size / 2 * (on and 1.06 or 1), 0, 2 * math.pi)
    cairo_fill(cr)
    cairo_set_source_rgb(cr, bg[1], bg[2], bg[3])
    if paused then
        triangle(cr, cx + size * 0.03, cy, size * 0.17, 1)
    else
        local gap, h = size * 0.12, size * 0.15
        rounded_line(cr, cx - gap, cy - h, cx - gap, cy + h, size * 0.1)
        rounded_line(cr, cx + gap, cy - h, cx + gap, cy + h, size * 0.1)
    end
end

local function draw_volume(cr, v, s)
    -- the speech volume: theme.draw_volume's slider, as the Spotify widget draws its own, its
    -- fraction the volume over speechctl's top of 2.0; while conky-mouse.py drags it, the
    -- level under the pointer from volume-preview
    local x0, x1, cy, fraction, ix, size = v[1] * s, v[2] * s, v[3] * s, v[4], v[5] * s, v[6] * s
    local preview = tonumber(read('volume-preview') or '')
    if preview then fraction = preview end
    local active = preview ~= nil or hovered(x0 - 6 * s, cy - 10 * s, x1 + 6 * s, cy + 10 * s)
    theme.draw_volume(cr, x0, x1, cy, fraction, ix, size, s, fg, active,
                      active or hovered(ix - 4 * s, cy - 10 * s, x1 + 6 * s, cy + 10 * s))
end

local function chevron(cr, cx, cy, h, s, up)
    -- a V (an upside-down one when `up`), the drop down's arrow
    local dy = up and -1 or 1
    cairo_move_to(cr, cx - h, cy - dy * h / 2)
    cairo_line_to(cr, cx, cy + dy * h / 2)
    cairo_line_to(cr, cx + h, cy - dy * h / 2)
    cairo_set_line_width(cr, 1.8 * s)
    cairo_set_line_join(cr, CAIRO_LINE_JOIN_ROUND)
    cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND)
    cairo_stroke(cr)
end

local function menu_state()
    -- {scroll, hover} while the voice list is open, else nil
    local text = read('voice-menu')
    if not text then return nil end
    local scroll, hover = text:match('^%s*(-?%d+)%s+(-?%d+)')
    return {scroll = tonumber(scroll) or 0, hover = tonumber(hover) or -1}
end

local function draw_voice(cr, v, label, s, text, open)
    -- the drop down: "Voice: amy" and an arrow in a pill of the foreground's tint, which
    -- the pointer or the open list darkens
    local x0, x1, cy, h, pad, arrow = v[1] * s, v[2] * s, v[3] * s, v[4] * s, v[5] * s, v[6] * s
    set(cr, fg, (open or hovered(v[1], v[3] - v[4] / 2, v[2], v[3] + v[4] / 2)) and 0.22 or 0.12)
    rounded_rect(cr, x0, cy - h / 2, x1 - x0, h, h / 2)
    cairo_fill(cr)
    font(cr, 11, text, s)
    set(cr, fg)
    show(cr, label, x0 + pad, cy, 'left')
    set(cr, fg)
    chevron(cr, x1 - pad - arrow / 2, cy, arrow / 3, s, open)
end

local function draw_menu(cr, m, items, s, text, state)
    -- the open voice list: a panel over the card, `rows` of the voices from state.scroll, the
    -- current one a pill of the foreground (as a selected segment is), the one under the pointer
    -- tinted, and a slim bar at the right when there are more voices than rows
    local x0, x1, top, bottom, item_h, rows, pad, count = m[1] * s, m[2] * s, m[3] * s, m[4] * s,
        m[5] * s, m[6], m[7] * s, m[8]
    rounded_rect(cr, x0, top, x1 - x0, bottom - top, 8 * s)
    cairo_set_source_rgb(cr, bg[1], bg[2], bg[3])
    cairo_fill_preserve(cr)
    set(cr, fg, 0.14)
    cairo_fill_preserve(cr)
    set(cr, fg, 0.35)
    cairo_set_line_width(cr, 1 * s)
    cairo_stroke(cr)
    font(cr, 11, text, s)
    for i = 0, rows - 1 do
        local item = items[state.scroll + i + 1]
        if not item then break end
        local y = top + pad + i * item_h
        if item.current then
            set(cr, fg)
            rounded_rect(cr, x0 + pad, y, x1 - x0 - 2 * pad, item_h, 5 * s)
            cairo_fill(cr)
            set(cr, fg_back)
        else
            if state.scroll + i == state.hover then
                set(cr, fg, 0.2)
                rounded_rect(cr, x0 + pad, y, x1 - x0 - 2 * pad, item_h, 5 * s)
                cairo_fill(cr)
            end
            set(cr, fg)
        end
        show(cr, item.label, x0 + pad + 6 * s, y + item_h / 2, 'left')
    end
    if count > rows then
        local ty0, ty1 = top + pad + 2 * s, bottom - pad - 2 * s
        local len = (ty1 - ty0) * rows / count
        local ty = ty0 + (ty1 - ty0 - len) * state.scroll / (count - rows)
        set(cr, fg, 0.3)
        rounded_line(cr, x1 - 4 * s, ty0, x1 - 4 * s, ty1, 3 * s)
        set(cr, fg)
        rounded_line(cr, x1 - 4 * s, ty, x1 - 4 * s, ty + len, 3 * s)
    end
end

local function confirm_state()
    -- {hover, busy, name} while the close prompt is open, else nil
    local text = read('close-confirm')
    if not text then return nil end
    local hover, busy, name = text:match('^%s*(%d)%s+(%d)\n?(.*)$')
    return {hover = tonumber(hover) or 0, busy = busy == '1', name = name or ''}
end

local function draw_confirm(cr, c, state, s, text)
    -- the close prompt: the list dimmed, and over it a panel (as the voice list's) with
    -- "Close <name>?", a line saying what that does, and Cancel and OK, OK in red
    local x0, top, x1, bottom = c[1] * s, c[2] * s, c[3] * s, c[4] * s
    local title_cy, msg_cy, button_cy, button_h = c[5] * s, c[6] * s, c[7] * s, c[8] * s
    local pad = 14 * s
    cairo_set_source_rgba(cr, bg[1], bg[2], bg[3], 0.7)
    cairo_rectangle(cr, c[13] * s, c[14] * s, (c[15] - c[13]) * s, (c[16] - c[14]) * s)
    cairo_fill(cr)
    rounded_rect(cr, x0, top, x1 - x0, bottom - top, 10 * s)
    cairo_set_source_rgb(cr, bg[1], bg[2], bg[3])
    cairo_fill_preserve(cr)
    set(cr, fg, 0.14)
    cairo_fill_preserve(cr)
    set(cr, fg, 0.35)
    cairo_set_line_width(cr, 1 * s)
    cairo_stroke(cr)
    local inner = x1 - x0 - 2 * pad
    font(cr, 11, text, s, true)
    set(cr, fg)
    local named = width_of(cr, 'Close ?')
    show(cr, 'Close ' .. fit(cr, state.name, inner - named) .. '?', x0 + pad, title_cy, 'left')
    font(cr, 9, text, s)
    set(cr, secondary())
    show(cr, fit(cr, state.busy and 'It is busy: closing it stops the turn it is in.' or 'This ends the session.',
                 inner), x0 + pad, msg_cy, 'left')
    font(cr, 11, text, s, true)
    local function button(bx0, bx1, label, on, red)
        rounded_rect(cr, bx0 * s, button_cy - button_h / 2, (bx1 - bx0) * s, button_h, button_h / 2)
        if red then
            cairo_set_source_rgba(cr, 0.78, 0.22, 0.18, on and 1 or 0.88)
        else
            set(cr, fg, on and 0.3 or 0.18)
        end
        cairo_fill(cr)
        if red then cairo_set_source_rgb(cr, 1, 1, 1) else set(cr, fg) end
        show(cr, label, (bx0 + bx1) / 2 * s, button_cy, 'centre')
    end
    button(c[9], c[10], 'Cancel', state.hover == 2, false)
    button(c[11], c[12], 'OK', state.hover == 1, true)
end

function conky_draw_widget()
    if conky_window == nil then return end
    local d = frame or load_draw()                 -- read once a frame, by the background hook
    frame = nil
    if not d.scale then return end
    local s, text = d.scale[1], d.scale[2] or 1

    -- the clip's clock: resync on each draw.txt update, advance locally in between
    local p = d.progress
    if p and p[4] ~= clock.stamp then
        clock = {stamp = p[4], pos = p[5], running = p[7] == 1}
    elseif p and clock.running then
        clock.pos = clock.pos + dt()
    end

    with_cairo(function(cr)
        cairo_translate(cr, margin, margin)        -- onto the card
        if d.window then draw_window_buttons(cr, d.window, s) end
        if d.header then draw_speaker(cr, d.header, s, d.state and d.state[1] or 'idle') end
        if p then draw_progress(cr, p, s, text, clock.pos) end
        if d.list and d.control and d.block then draw_list(cr, d.list, d.text.list:match('^' .. ('%S+%s+'):rep(5) .. '(%S+)'), d.control, d.block, s, text) else scroll = nil end
        if d.footer then draw_footer(cr, d.footer, s) end
        if d.buttons then draw_skip_buttons(cr, d.buttons, s) end
        if d.volume then draw_volume(cr, d.volume, s) end
        local menu = d.menu and #d.items > 0 and menu_state()
        if d.voice then draw_voice(cr, d.voice, label_after(d.text.voice, 6), s, text, menu and true or false) end
        if menu then draw_menu(cr, d.menu, d.items, s, text, menu) end
        local confirm = d.confirm and confirm_state()
        if confirm then draw_confirm(cr, d.confirm, confirm, s, text) end
    end)
end
