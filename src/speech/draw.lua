-- Cairo drawing for the speech widget, fed by speechqueue.py:
--   draw.txt      geometry (logical px, from the card's top left); its scale line is the
--                 display's scale and the text scale, its shadow line the margin round the card
--   widget.txt    conky's markup (the column headers), shown through conky_widget
--   sessions.txt  the sessions list, a line per session, reread when draw.txt names a new version
--   list-scroll   how many rows conky-mouse.py has scrolled the list down; 0 until it has
--   bubble-scroll how many lines conky-mouse.py has turned the wheel over the speech bubble, in all
--                 (down counts up); the bubble follows the clip again BUBBLE_HOLD seconds after the last
--   volume-preview  the volume under the pointer while conky-mouse.py drags the volume slider
--   settings-menu present while conky-mouse.py has the settings menu open: the selected row and
--                 how many rows it is scrolled, as "<selected> <scrolled>", the page's title, then
--                 a row a line, "<label>\t<value>\t<flag>"
--   close-confirm present while conky-mouse.py has the close prompt open: the button under the
--                 pointer (0 none, 1 OK, 2 Cancel) and whether the session is busy, then its name
-- The colours are Claude's CLI's own and fixed: white text and its shares on a near-black
-- card, with the CLI's orange for the terminal pane's border, its code and its spinner.
require 'cairo'
pcall(require, 'cairo_xlib')

-- The shared drawing helpers sit in ../common, installed or in a checkout.
local here = debug.getinfo(1, 'S').source:match('^@(.*)/[^/]*$')
    or (os.getenv('CSN_DIR') or '/usr/share/conky-widgets') .. '/speech'
package.path = here .. '/../common/?.lua;' .. package.path
local theme = require 'theme'
local set, rounded_rect = theme.set, theme.rounded_rect

local cache = os.getenv('HOME') .. '/.cache/conky-widgets/speech/'
local FONT = 'Ubuntu Sans'
local hover_x, hover_y = -1, -1           -- window px
local margin = 0                          -- the shadow margin around the card, in window px
local frame = nil                         -- draw.txt as the background hook read it this frame
local bg = {0.094, 0.094, 0.094}          -- the card's colour, #181818
local fg, fg_back = theme.LIGHT, theme.DARK   -- fg_back: drawn on fg, like the pause icon
local clock = {stamp = nil, pos = 0, duration = 0, running = false}
local sessions = {version = nil, rows = {}}
local scroll = nil                        -- eased list scroll position, in rows
local said = {shown = nil, target = 0, follow = true, steps = nil}   -- the terminal's text: its eased offset in lines, where the wheel left it, whether it follows the newest line
local TERM_WHEEL = 3                      -- lines a wheel step scrolls the terminal

local function read(name)
    local f = io.open(cache .. name)
    if not f then return nil end
    local s = f:read('*a')
    f:close()
    return s
end

local function load_draw()
    -- {key = {numbers...}}, and each line's own text in d.text[key]
    local d = {text = {}, lines = {}}
    for line in (read('draw.txt') or ''):gmatch('[^\n]+') do
        local key, rest = line:match('^(%S+) (.*)$')    -- one space: a bubble line's own indent is kept
        if key == 'line' then
            d.lines[#d.lines + 1] = rest
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
    -- sessions.txt's lines (speechqueue.py's session_line) as {id, speech, speaking, queued,
    -- flags, name, repo, span, header}
    if version == sessions.version then return end
    local rows = {}
    for line in (read('sessions.txt') or ''):gmatch('[^\n]+') do
        local f = {}
        for v in (line .. '\t'):gmatch('([^\t]*)\t') do f[#f + 1] = v end
        rows[#rows + 1] = {id = f[1] or '', speech = f[2], speaking = f[3] == '1', queued = tonumber(f[4]) or 0,
                           flags = (f[5] or '-') ~= '-' and f[5]:gsub(',', ' ') or '',
                           name = f[6] or '', repo = f[7] or '',
                           span = tonumber(f[8]) or 1, header = f[9] or ''}
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

function conky_widget()
    -- conky.text: speechqueue.py's markup
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
        if d.divider then                          -- the terminal's column, between the header and footer, a shade darker than the sessions'
            local x = margin + d.divider[1] * s
            local y0, y1 = margin + d.divider[2] * s, margin + d.divider[3] * s
            cairo_set_source_rgba(cr, 0, 0, 0, 0.22)
            cairo_rectangle(cr, x, y0, margin + w - x, y1 - y0)
            cairo_fill(cr)
        end
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

local function font(cr, pt, text, s, bold, italic, mono)
    cairo_select_font_face(cr, mono and 'Ubuntu Mono' or FONT,
                           italic and CAIRO_FONT_SLANT_ITALIC or CAIRO_FONT_SLANT_NORMAL,
                           bold and CAIRO_FONT_WEIGHT_BOLD or CAIRO_FONT_WEIGHT_NORMAL)
    cairo_set_font_size(cr, pt * text * 96 / 72 * s)
    face = (bold and 'b' or '') .. (italic and 'i' or '') .. (mono and 'm' or '') .. pt * text * s
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

local function draw_title(cr, t, label, s, text)
    -- the widget's name, from x = t[1] and centred on y = t[2], with t[3] em between letters
    local x, cy = t[1] * s, t[2] * s
    font(cr, 11, text, s, true)
    set(cr, fg)
    local track = t[3] * 11 * text * 96 / 72 * s
    cairo_font_extents(cr, fext)
    for _, c in utf8.codes(label) do
        local ch = utf8.char(c)
        cairo_move_to(cr, x, cy + (fext.ascent - fext.descent) / 2)
        cairo_show_text(cr, ch)
        x = x + width_of(cr, ch) + track
    end
end

local ORANGE = {0.843, 0.467, 0.341}      -- Claude's CLI's orange (215, 119, 87)
local SPARK = {1, 0.74, 0.92, 0.78, 1, 0.74, 0.92, 0.78, 1, 0.74, 0.92, 0.78}   -- ray lengths, as shares of the longest

local function draw_spark(cr, cx, cy, r, phase, alpha, color)
    -- the CLI's spinner: twelve rays of uneven length, in its orange unless `color` says another, turned by `phase`
    set(cr, color or ORANGE, alpha)
    for i, share in ipairs(SPARK) do
        local angle = (i - 1) * math.pi / 6 - math.pi / 2 + phase
        rounded_line(cr, cx + 0.15 * r * math.cos(angle), cy + 0.15 * r * math.sin(angle),
                     cx + r * share * math.cos(angle), cy + r * share * math.sin(angle), 0.2 * r)
    end
end

local function term_offset(count, shown_lines)
    -- how many lines the terminal's text is scrolled, from its top: at the end, following the
    -- newest line as it is printed, until the wheel moves it up; scrolled back to the end it
    -- follows again. Eased between.
    local last = math.max(count - shown_lines, 0)
    local steps = tonumber((read('terminal-scroll') or ''):match('^%s*(%S+)') or '') or 0   -- no file: no steps yet
    if said.steps == nil then said.steps = steps end
    if said.shown == nil then said.shown = last end
    if said.follow then said.target = last end
    if steps ~= said.steps then
        said.target = math.min(math.max(said.target + (steps - said.steps) * TERM_WHEEL, 0), last)
        said.follow = said.target >= last
        said.steps = steps
    end
    said.target = math.min(said.target, last)
    said.shown = said.shown + (said.target - said.shown) * (1 - math.exp(-dt() * 12 / 1.1))
    return said.shown
end

local BULLET_MARK, PROMPT_MARK, DONE_MARK, META_MARK = 2, 4, 5, '\6'   -- speechqueue.py's: a line's first byte, for the first line of a message's text, its speaker's name and its closing line
local STYLE_MARK = '\31'                   -- speechqueue.py's: before each run of a styled line, its style letter

local function mono(cr, text, s, bold, italic)
    font(cr, 12, text, s, bold, italic, true)
end

local function show_line(cr, line, x, cy, s, text, alpha)
    -- a terminal line: plain text, or runs each led by STYLE_MARK and a style letter (n normal,
    -- b bold, i italic, x both, c code in the CLI's orange) drawn one after another on the
    -- baseline the normal font gives; returns where it ends
    mono(cr, text, s)
    cairo_font_extents(cr, fext)
    local base = cy + (fext.ascent - fext.descent) / 2
    if not line:find(STYLE_MARK, 1, true) then
        set(cr, fg, alpha)
        cairo_move_to(cr, x, base)
        cairo_show_text(cr, line)
        return x + width_of(cr, line)
    end
    for style, run in line:gmatch(STYLE_MARK .. '(%a)([^' .. STYLE_MARK .. ']*)') do
        mono(cr, text, s, style == 'b' or style == 'x', style == 'i' or style == 'x')
        if style == 'c' then set(cr, ORANGE, alpha) else set(cr, fg, alpha) end
        cairo_move_to(cr, x, base)
        cairo_show_text(cr, run)
        x = x + width_of(cr, run)
    end
    return x
end

local function fmt_time(sec)
    sec = math.floor(math.max(sec, 0))
    return string.format('%d:%02d', sec // 60, sec % 60)
end

local MASCOT = {' \u{2590}\u{259b}\u{2588}\u{2588}\u{2588}\u{259c}\u{258c}',
                '\u{259d}\u{259c}\u{2588}\u{2588}\u{2588}\u{2588}\u{2588}\u{259b}\u{2598}',
                '  \u{2598}\u{2598} \u{259d}\u{259d}'}   -- Claude Code's creature, as its banner sets it in block characters
local QUADRANTS = {['\u{2590}'] = {0, 1, 0, 1}, ['\u{259b}'] = {1, 1, 1, 0}, ['\u{2588}'] = {1, 1, 1, 1},
                   ['\u{259c}'] = {1, 1, 0, 1}, ['\u{258c}'] = {1, 0, 1, 0}, ['\u{259d}'] = {0, 1, 0, 0},
                   ['\u{2598}'] = {1, 0, 0, 0}}   -- which quarters (upper left, upper right, lower left, lower right) a block character fills

local function draw_mascot(cr, x, cy, cw, step)
    -- the creature's rows on the terminal's grid, each block character drawn as its filled
    -- quarters of a cell (the terminal font has no quadrant glyphs), the first row centred on cy
    set(cr, ORANGE)
    cairo_new_path(cr)
    for i, row in ipairs(MASCOT) do
        local top, n = cy + (i - 1.5) * step, 0
        for _, c in utf8.codes(row) do
            local q = QUADRANTS[utf8.char(c)]
            if q then
                for k = 0, 3 do
                    if q[k + 1] == 1 then
                        cairo_rectangle(cr, x + n * cw + (k % 2) * cw / 2, top + (k // 2) * step / 2, cw / 2, step / 2)
                    end
                end
            end
            n = n + 1
        end
    end
    cairo_fill(cr)
end

local function draw_chevron(cr, x, cy, h, alpha, color)
    -- the prompt's "❯", drawn rather than set in a font that may not have it
    set(cr, color or fg, alpha)
    cairo_set_line_width(cr, 1.3 * h / 8)
    cairo_new_path(cr)
    cairo_move_to(cr, x, cy - h / 2)
    cairo_line_to(cr, x + h / 2.4, cy)
    cairo_line_to(cr, x, cy + h / 2)
    cairo_stroke(cr)
end

local links_written = ''

local function write_links(links)
    -- the issue and pull request numbers drawn this frame, each "<line> <number> x0 y0 x1 y1" in
    -- logical px, for mouse.py to find the one under a click; rewritten only when they move
    local rows = {}
    for _, l in ipairs(links) do
        rows[#rows + 1] = string.format('%d %d %.1f %.1f %.1f %.1f', l[1], l[2], l[3], l[4], l[5], l[6])
    end
    local out = table.concat(rows, '\n')
    if out == links_written then return end
    links_written = out
    local f = io.open(cache .. 'terminal-links', 'w')
    if f then f:write(out) f:close() end
end

local function draw_meta(cr, meta, right, y, line, step, s, text, links)
    -- the "[ Issue #1, #2 | PR #3 ]" a prompt line carries, right-aligned at `right`: its words
    -- dim, each number a link, bold and brighter under the pointer; the numbers' places
    -- go into `links`
    local segments, total = {}, 0
    mono(cr, text, s)
    for kind, str in meta:gmatch(META_MARK .. '(%a)([^' .. META_MARK .. ']*)') do
        segments[#segments + 1] = {kind, str, width_of(cr, str)}
        total = total + segments[#segments][3]
    end
    local x, number = right - total, 0
    for _, seg in ipairs(segments) do
        local kind, str, w = seg[1], seg[2], seg[3]
        if kind == 'k' then
            number = number + 1
            local on = hovered(x, y - step / 2, x + w, y + step / 2)
            set(cr, fg, on and 1 or 0.85)
            mono(cr, text, s, true)
            show(cr, str, x, y, 'left')
            mono(cr, text, s)
            links[#links + 1] = {line, number, x / s, (y - step / 2) / s, (x + w) / s, (y + step / 2) / s}
        else
            set(cr, fg, 0.5)
            show(cr, str, x, y, 'left')
        end
        x = x + w
    end
end

local function draw_working(cr, left, cw, y, s, pos, duration, paused, queued, playing)
    -- the CLI's working line: the orange spinner turning and "Reading aloud…" with the clip's
    -- time, or "Paused" (still, dimmer), or "Waiting" while lines queue and none plays
    if playing == nil then playing = true end
    local working = playing and not paused
    draw_spark(cr, left + 0.55 * cw, y, 5.5 * s, working and pos * 3 or 0, working and 1 or 0.6)
    local label = playing and (paused and 'Paused' or 'Reading aloud\u{2026}') or 'Waiting'
    set(cr, ORANGE, working and 1 or 0.6)
    local lw = show(cr, label, left + 2 * cw, y, 'left')
    local detail = {}
    if playing then detail[#detail + 1] = fmt_time(math.min(pos, duration > 0 and duration or pos)) .. ' / ' .. fmt_time(duration) end
    if queued > 0 then detail[#detail + 1] = queued .. ' queued' end
    if #detail > 0 then
        set(cr, fg, 0.5)
        show(cr, '(' .. table.concat(detail, ' \u{b7} ') .. ')', left + 2 * cw + lw + cw, y, 'left')
    end
end

local function draw_terminal(cr, t, title, lines, s, text, scrolled, pos, duration)
    -- the pane as Claude's CLI prints a session, with no frame of its own: its welcome banner
    -- (the creature, then the pane's title and what the widget is holding), then each message
    -- spoken so far, printed when it began to be read, scrolling like a terminal's. A message is
    -- the CLI's own three parts: the speaker's name on a grey band behind a "❯" as the prompt,
    -- the text behind a white bullet, and a dim "✻ Read aloud for 7s · done Thursday 9:47 AM" line.
    -- t[9] lines show at once, the rest above them scrolled by `scrolled` lines and clipped to
    -- where they show. While a clip plays, the closing line of the message being read is the
    -- CLI's working line (the spinner turning and "Reading aloud…" with the clip's time, or
    -- "Paused"), and turns into its gray line with the time once it is done.
    local x0, x1, pad = t[1] * s, t[3] * s, t[5] * s
    local head_cy, first_cy, step, shown, status_cy = t[6] * s, t[7] * s, t[8] * s, t[9], t[10] * s
    local playing, paused, queued = t[11] == 1, t[12] == 1, t[13]
    local sessions, speech_on = t[14] or 0, t[15] or 0
    local left = x0 + pad

    mono(cr, text, s)
    local cw = width_of(cr, ' ')
    draw_mascot(cr, left, head_cy, cw, step)              -- the banner: the creature on the terminal's grid, then three lines
    local tx = left + 12 * cw
    mono(cr, text, s, true)
    set(cr, fg)
    show(cr, fit(cr, title, x1 - pad - tx), tx, head_cy, 'left')
    mono(cr, text, s)
    set(cr, fg, 0.5)
    show(cr, sessions .. (sessions == 1 and ' session' or ' sessions') .. ' \u{b7} ' .. speech_on .. ' with speech on', tx, head_cy + step, 'left')
    show(cr, queued > 0 and (queued .. (queued == 1 and ' line queued' or ' lines queued')) or 'Nothing queued', tx, head_cy + 2 * step, 'left')

    local reading = nil                                    -- the closing line of the message being read, which turns into the working line
    if playing then
        for i, line in ipairs(lines) do
            if line:byte(1) == DONE_MARK then reading = i end
        end
        if reading and reading ~= #lines then reading = nil end
    end

    local ytop = first_cy - step / 2
    local links_now = {}                                   -- the numbers drawn this frame, for mouse.py to hit-test
    cairo_save(cr)
    cairo_rectangle(cr, x0, ytop, x1 - x0, shown * step)
    cairo_clip(cr)
    for i, line in ipairs(lines) do
        local y = first_cy + (i - 1 - scrolled) * step
        if y > first_cy - step and y < first_cy + shown * step then
            local kind = line:byte(1)
            if kind == BULLET_MARK or kind == PROMPT_MARK or kind == DONE_MARK then line = line:sub(2) end
            if kind == PROMPT_MARK then
                set(cr, fg, 0.14)                           -- the prompt's grey band, edge to edge
                cairo_rectangle(cr, x0, y - step / 2, x1 - x0, step)
                cairo_fill(cr)
                draw_chevron(cr, left + 0.2 * cw, y, step * 0.5, 0.6)
                local name, meta = line:match('^([^\6]*)(.*)$')
                show_line(cr, name, left + 2 * cw, y, s, text, 1)
                draw_meta(cr, meta, x1 - pad, y, i - 1, step, s, text, links_now)
            elseif kind == DONE_MARK and i == reading then
                draw_working(cr, left, cw, y, s, pos, duration, paused, queued)
            elseif kind == DONE_MARK then
                draw_spark(cr, left + 0.55 * cw, y, 4.2 * s, 0, 0.55, fg)      -- gray, as the CLI's is once its turn is done
                show_line(cr, line, left + 2 * cw, y, s, text, 0.5)
            else
                show_line(cr, line, left, y, s, text, 1)
                if kind == BULLET_MARK then
                    set(cr, fg)
                    cairo_new_path(cr)
                    cairo_arc(cr, left + 0.55 * cw, y, 3.2 * s, 0, 2 * math.pi)
                    cairo_fill(cr)
                end
            end
        end
    end
    cairo_restore(cr)

    write_links(links_now)
    -- the working line has a row of its own only when no message is being read: lines waiting,
    -- or a clip playing before its message is printed
    if reading or not (playing or queued > 0) then return end
    draw_working(cr, left, cw, status_cy, s, pos, duration, paused, queued, playing)
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

local function list_offset(last)
    local offset = tonumber((read('list-scroll') or ''):match('^%s*(%S+)') or '') or 0
    return math.min(math.max(offset, 0), last)
end

local function draw_divider(cr, v, rules, s, w)
    -- the lines of the application's frame, as Claude's app draws its own: one thin line a little
    -- lighter than the card under the header across the card, another over the controls at the
    -- foot of the sessions column, and the divider between the columns from the first to the
    -- card's bottom, brighter while it is being dragged (mouse.py's divider-drag file)
    local x, y0, y1 = v[1] * s, v[2] * s, v[3] * s
    local held = read('divider-drag') ~= nil
    cairo_set_line_width(cr, math.max(1, math.floor(s + 0.5)))
    set(cr, fg, 0.14)
    for _, line in ipairs({{rules[1], w}, {rules[2], x}}) do
        local y = math.floor(line[1] * s) + 0.5
        cairo_new_path(cr)
        cairo_move_to(cr, 0, y)
        cairo_line_to(cr, line[2], y)
        cairo_stroke(cr)
    end
    set(cr, fg, held and 0.4 or 0.14)
    cairo_new_path(cr)
    cairo_move_to(cr, math.floor(x) + 0.5, y0)
    cairo_line_to(cr, math.floor(x) + 0.5, y1)
    cairo_stroke(cr)
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

local glows = {}                            -- session id -> how bright its row is, 0 to 1

local SPEECH_SETTINGS = {{'on', 'On'}, {'alerts', 'Alerts'}, {'off', 'Off'}}
local function draw_gear(cr, g, s, open)
    -- the gear at the footer's right, opening the settings menu: a ring with eight teeth in the
    -- foreground, brighter under the pointer
    local cx, cy, size = g[1] * s, g[2] * s, g[3] * s
    local on = hovered(cx - size, cy - size, cx + size, cy + size)
    local r, teeth = size * 0.32, 8
    set(cr, fg, (on or open) and 1 or 0.7)
    cairo_set_line_width(cr, size * 0.17)
    cairo_new_path(cr)
    cairo_arc(cr, cx, cy, r, 0, 2 * math.pi)
    cairo_stroke(cr)
    cairo_set_line_cap(cr, CAIRO_LINE_CAP_BUTT)
    for i = 0, teeth - 1 do
        local a = i * 2 * math.pi / teeth
        cairo_set_line_width(cr, size * 0.2)
        cairo_move_to(cr, cx + math.cos(a) * r, cy + math.sin(a) * r)
        cairo_line_to(cr, cx + math.cos(a) * size * 0.5, cy + math.sin(a) * size * 0.5)
        cairo_stroke(cr)
    end
end

local GREEN = {0.33, 0.78, 0.40}          -- the CLI's dot before a finished item

local function draw_group(cr, r, x0, y, row, c, b, s, text)
    -- a section's title on a row of its own above the first session listed under it, as the CLI
    -- sets its session list: "Working" dim, the others bold and bright
    local x = x0 + b[1] * s
    if r.header == 'Working' then
        mono(cr, text, s)
        set(cr, secondary())
    else
        mono(cr, text, s, true)
        set(cr, fg)
    end
    show(cr, fit(cr, r.header, c[1] * s - x - 4 * s), x, y + row / 2, 'left')
end

local function draw_row(cr, r, x0, y, row, c, s, text, blk)
    -- a session's line, set as the CLI sets its session list, in the terminal's font: behind a
    -- small green dot, or the turning spinner and a bold name while it is busy, its name dim
    -- unless it is busy or being read aloud; then dim after it its repository, and at the right the lines it has queued (a click on
    -- the name asks to close the session). A section's title above it
    -- when it is the first listed under that, after a blank row unless it is the first section.
    -- Its issue and pull request numbers are in its messages' headers in the terminal. The name
    -- is underlined under the pointer. Returns how many rows it took.
    local head_rows = r.header ~= '' and r.span - 1 or 0
    if head_rows > 0 then
        draw_group(cr, r, x0, y + (head_rows - 1) * row, row, c, blk, s, text)
        y = y + head_rows * row
    end
    local cy = y + row / 2
    local name_x = x0 + (blk[1] + blk[2]) * s
    local bullet_x = x0 + blk[1] * s + 13 * s
    local busy = r.flags == 'busy'
    if busy then
        draw_spark(cr, bullet_x, cy, 5 * s, os.clock() * 3, 1, fg)
    else
        set(cr, GREEN)
        cairo_new_path(cr)
        cairo_arc(cr, bullet_x, cy, 1.8 * s, 0, 2 * math.pi)
        cairo_fill(cr)
    end
    font(cr, 11, text, s, false, false, true)
    local queued = r.queued > 0 and r.queued .. ' queued' or ''
    local queued_w = queued ~= '' and width_of(cr, queued) + 8 * s or 0
    local right = c[2] * s - queued_w
    mono(cr, text, s, busy)
    local name = fit(cr, r.name, right - name_x)
    local after = name_x + width_of(cr, name)
    if hovered(name_x - 4 * s, cy - row / 2, after + 4 * s, cy + row / 2) then
        set(cr, fg, 0.6)
        cairo_set_line_width(cr, 1 * s)
        cairo_move_to(cr, name_x, cy + row * 0.34)
        cairo_line_to(cr, after, cy + row * 0.34)
        cairo_stroke(cr)
    end
    if busy or r.speaking then set(cr, fg) else set(cr, secondary()) end
    show(cr, name, name_x, cy, 'left')

    font(cr, 11, text, s, false, false, true)
    set(cr, secondary(), 0.7)
    local detail = r.repo                            -- the section it is under says its state
    local dx = after + 12 * s
    if detail ~= '' and right - dx > 40 * s then show(cr, fit(cr, detail, right - dx), dx, cy, 'left') end
    if queued ~= '' then show(cr, queued, c[2] * s, cy, 'right') end
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
        draw_scrollbar(cr, x1 + 4 * s, top, height, s, height / row, total, scroll, last)
    end
    local seen = {}
    for _, r in ipairs(rows) do                    -- each row brightens and dims over about a third of a second
        local to = r.speaking and 1 or 0
        local now = glows[r.id] or to
        now = now + (to - now) * (1 - math.exp(-dt() * 10 / 1.1))
        glows[r.id] = math.abs(to - now) < 0.01 and to or now
        seen[r.id] = true
    end
    for id in pairs(glows) do
        if not seen[id] then glows[id] = nil end
    end
    cairo_save(cr)
    cairo_rectangle(cr, x0, top, x1 - x0, height)
    cairo_clip(cr)
    local at = 0
    for _, r in ipairs(rows) do
        local y = top + (at - scroll) * row
        if y > top + height then break end
        local glow = glows[r.id] or 0              -- the row being read aloud, brighter
        if glow > 0 then
            set(cr, fg, glow * 0.2)
            rounded_rect(cr, x0, y, x1 - x0, r.span * row, 6 * s)
            cairo_fill(cr)
        end
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

local function menu_state()
    -- {selected, top, title, rows = {{label, value, flag}}} while the settings menu is open, else nil
    local text = read('settings-menu')
    if not text then return nil end
    local head, title, rest = text:match('^(%d+ %d+)\n([^\n]*)\n?(.*)$')
    if not head then return nil end
    local selected, top = head:match('^(%d+) (%d+)$')
    local rows = {}
    for line in rest:gmatch('[^\n]+') do
        local label, value, flag = line:match('^([^\t]*)\t?([^\t]*)\t?([^\t]*)$')
        rows[#rows + 1] = {label or '', value or '', flag or ''}
    end
    return {selected = tonumber(selected), top = tonumber(top), title = title, rows = rows}
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

local MENU_SELECTED = {0.69, 0.73, 0.98}     -- the CLI's selection colour, its cursor and the row it is on

local function draw_menu(cr, m, state, s, text)
    -- the settings menu, laid out as the CLI's settings list over the card below its title: the
    -- page's title on a first line (a click on it goes back), a row for each setting with its
    -- value at the right and the selected one behind a cursor in the selection colour, and the
    -- keys at the foot
    local x0, top, x1, bottom = m[1] * s, m[2] * s, m[3] * s, m[4] * s
    local title_cy, first, row, visible, hint_cy, value_x, pad = m[5] * s, m[6] * s, m[7] * s, m[8], m[9] * s, m[10] * s, m[11] * s
    local card_w, card_h = conky_window.width - 2 * margin, conky_window.height - 2 * margin
    cairo_save(cr)
    rounded_rect(cr, 0, 0, card_w, card_h, math.min(24, card_h / 4))
    cairo_clip(cr)
    cairo_set_source_rgb(cr, bg[1], bg[2], bg[3])
    cairo_rectangle(cr, 0, top, card_w, card_h - top)
    cairo_fill(cr)
    cairo_restore(cr)
    set(cr, fg, 0.12)
    cairo_set_line_width(cr, 1 * s)
    cairo_move_to(cr, 0, top)
    cairo_line_to(cr, card_w, top)
    cairo_stroke(cr)
    local left = x0 + pad
    mono(cr, text, s, true)
    set(cr, fg, 0.9)
    show(cr, fit(cr, state.title, x1 - left - pad), left, title_cy, 'left')
    local total = #state.rows
    for i = state.top + 1, math.min(state.top + visible, total) do
        local r = state.rows[i]
        local cy = first + (i - state.top - 1) * row + row / 2
        local on = i == state.selected + 1
        mono(cr, text, s)
        if on then draw_chevron(cr, left + 0.2 * width_of(cr, ' '), cy, row * 0.5, 1, MENU_SELECTED) end
        local function colour(dim)
            if on then
                cairo_set_source_rgb(cr, MENU_SELECTED[1], MENU_SELECTED[2], MENU_SELECTED[3])
            else
                set(cr, fg, dim and 0.55 or 1)
            end
        end
        colour(false)
        show(cr, fit(cr, r[1], value_x - left - 3 * pad), left + 2 * width_of(cr, ' '), cy, 'left')
        if r[2] ~= '' then
            if r[3] == 'current' and not on then set(cr, GREEN) else colour(r[2] == '\u{203a}') end
            show(cr, fit(cr, r[2], x1 - value_x - pad), value_x, cy, 'left')
        end
    end
    mono(cr, text, s)
    set(cr, fg, 0.5)
    local function arrow(cy, dir)                  -- a small triangle at the right edge: more rows above (-1) or below (1)
        local ax, h = x1 - pad - 4 * s, 3 * s
        cairo_new_path(cr)
        cairo_move_to(cr, ax - h, cy + dir * h / 2)
        cairo_line_to(cr, ax + h, cy + dir * h / 2)
        cairo_line_to(cr, ax, cy - dir * h / 2)
        cairo_close_path(cr)
        cairo_fill(cr)
    end
    if state.top > 0 then arrow(first + row / 2, 1) end
    if state.top + visible < total then arrow(first + (visible - 0.5) * row, -1) end
    show(cr, fit(cr, 'Enter/Space to change \u{b7} Backspace to go back \u{b7} Esc to close', x1 - left - pad), left, hint_cy, 'left')
end

function conky_draw_widget()
    if conky_window == nil then return end
    local d = frame or load_draw()                 -- read once a frame, by the background hook
    frame = nil
    if not d.scale then return end
    local s, text = d.scale[1], d.scale[2] or 1

    -- the clip's clock: resync on each draw.txt update, advance locally in between
    local p = d.clock
    if p and p[1] ~= clock.stamp then
        clock = {stamp = p[1], pos = p[2], duration = p[3], running = p[4] == 1}
    elseif p and clock.running then
        clock.pos = clock.pos + dt()
    end

    with_cairo(function(cr)
        cairo_translate(cr, margin, margin)        -- onto the card
        if d.window then draw_window_buttons(cr, d.window, s) end
        if d.title then draw_title(cr, d.title, label_after(d.text.title, 3), s, text) end
        if d.terminal then
            draw_terminal(cr, d.terminal, d.text.speaker or '', d.lines, s, text,
                          term_offset(#d.lines, d.terminal[9]), clock.pos, clock.duration)
        end
        if d.list and d.control and d.block then draw_list(cr, d.list, d.text.list:match('^' .. ('%S+%s+'):rep(5) .. '(%S+)'), d.control, d.block, s, text) else scroll = nil end
        if d.divider then draw_divider(cr, d.divider, d.rules, s, conky_window.width - 2 * margin) end
        if d.footer then draw_footer(cr, d.footer, s) end
        if d.buttons then draw_skip_buttons(cr, d.buttons, s) end
        if d.volume then draw_volume(cr, d.volume, s) end
        local menu = d.menu and menu_state()
        if d.gear then draw_gear(cr, d.gear, s, menu ~= nil) end
        if menu then draw_menu(cr, d.menu, menu, s, text) end
        local confirm = d.confirm and confirm_state()
        if confirm then draw_confirm(cr, d.confirm, confirm, s, text) end
    end)
end
