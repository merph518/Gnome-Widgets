-- Drawing and colour helpers every conky widget here shares: the card and its shadow, and the
-- foreground that follows a fading background by APCA contrast. A widget's draw.lua loads it
-- with require, from this directory, and keeps its own state (the background, the foreground).
local theme = {}

-- Foreground: white on dark or saturated backgrounds, near-black on light ones, whichever
-- contrasts more with the background as it fades (nowplaying.py's LIGHT_FG and DARK_FG).
-- nowplaying.py only picks backgrounds on which one of the two reaches APCA Lc 60.
theme.LIGHT, theme.DARK = {1, 1, 1}, {0.07, 0.07, 0.07}

function theme.apca_y(c)
    -- APCA's screen luminance, soft-clamped near black (nowplaying.py's apca_y)
    local y = 0.2126729 * c[1] ^ 2.4 + 0.7151522 * c[2] ^ 2.4 + 0.0721750 * c[3] ^ 2.4
    if y < 0.022 then y = y + (0.022 - y) ^ 1.414 end
    return y
end

function theme.contrast(text, back)
    -- APCA lightness contrast of text on back as |Lc|, as nowplaying.py's contrast
    local yt, yb = theme.apca_y(text), theme.apca_y(back)
    if math.abs(yb - yt) < 0.0005 then return 0 end
    if yb > yt then
        local sapc = (yb ^ 0.56 - yt ^ 0.57) * 1.14
        return sapc < 0.1 and 0 or (sapc - 0.027) * 100
    end
    local sapc = (yb ^ 0.65 - yt ^ 0.62) * 1.14
    return sapc > -0.1 and 0 or -(sapc + 0.027) * 100
end

function theme.mix(a, b, t)
    return {a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, a[3] + (b[3] - a[3]) * t}
end

function theme.secondary(fg, bg)
    -- the artist and the times: the foreground up to a fifth of the way into the background
    -- (on Spotify's #181818 that is d0d0d0), less where that would drop it under Lc 60
    for t = 0.2, 0.01, -0.02 do
        local c = theme.mix(fg, bg, t)
        if theme.contrast(c, bg) >= 60 then return c end
    end
    return fg
end

function theme.set(cr, c, a)
    cairo_set_source_rgba(cr, c[1], c[2], c[3], a or 1)
end

function theme.now()
    -- seconds since boot, to 0.01 s: the clock every conky process here shares, which
    -- art_colours.py writes bg.txt's start time on (CLOCK_BOOTTIME); os.time counts whole seconds
    local f = io.open('/proc/uptime')
    local s = f and f:read('*l') or ''
    if f then f:close() end
    return tonumber(s:match('^(%S+)')) or 0
end

-- This boot's id, which bg.txt carries beside its start time, since the clock restarts at
-- each boot. It cannot change while conky runs, so it is read once.
theme.BOOT = (function()
    local f = io.open('/proc/sys/kernel/random/boot_id')
    local s = f and f:read('*l') or ''
    if f then f:close() end
    return s
end)()

local function numbers(words, n)
    -- the first n of words as numbers, or nil unless every one is
    local t = {}
    for i = 1, n do
        t[i] = tonumber(words[i])
        if not t[i] then return nil end
    end
    return t
end

function theme.fade(bg, path)
    -- bg (changed in place) where the ~1 s fade towards the colour in path has got to by now,
    -- and the foreground for it and the colour drawn on that foreground. path is the Spotify
    -- widget's bg.txt, 'r g b  from_r from_g from_b  start boot_id' (colours from 0 to 1),
    -- whose fade both widgets work out from the same numbers and so show alike in every frame;
    -- a start from another boot is long finished. A file with only 'r g b' (the speech
    -- widget's background setting can name one), or none, which fades to Spotify's #181818,
    -- starts its fade here, from the colour shown when it changed.
    local f = io.open(path)
    local s = f and f:read('*l') or ''
    if f then f:close() end
    local words = {}
    for w in s:gmatch('%S+') do words[#words + 1] = w end
    local v, now = numbers(words, 7), theme.now()
    local to, from, t0
    if v and words[8] then
        to, from, t0 = {v[1], v[2], v[3]}, {v[4], v[5], v[6]}, v[7]
        if words[8] ~= theme.BOOT then from = to end
        bg.target = nil
    else
        to = numbers(words, 3) or {0.094, 0.094, 0.094}
        local key = table.concat(to, ' ')
        if bg.target ~= key then
            bg.target, bg.from, bg.start = key, {bg[1], bg[2], bg[3]}, now
        end
        from, t0 = bg.from, bg.start
    end
    local k = 1 - math.exp(-math.max(now - t0, 0) * 3)
    for i = 1, 3 do bg[i] = from[i] + (to[i] - from[i]) * k end
    if theme.contrast(theme.LIGHT, bg) >= theme.contrast(theme.DARK, bg) then
        return theme.LIGHT, theme.DARK
    end
    return theme.DARK, theme.LIGHT
end

function theme.conky_colour(c)
    -- c as conky markup, for a widget's ${lua_parse fg ...}
    return string.format('${color %02x%02x%02x}', math.floor(c[1] * 255 + 0.5),
                         math.floor(c[2] * 255 + 0.5), math.floor(c[3] * 255 + 0.5))
end

function theme.rounded_rect(cr, x, y, w, h, rad)
    cairo_new_sub_path(cr)
    cairo_arc(cr, x + w - rad, y + rad, rad, -math.pi / 2, 0)
    cairo_arc(cr, x + w - rad, y + h - rad, rad, 0, math.pi / 2)
    cairo_arc(cr, x + rad, y + h - rad, rad, math.pi / 2, math.pi)
    cairo_arc(cr, x + rad, y + rad, rad, math.pi, 3 * math.pi / 2)
    cairo_close_path(cr)
end

local function rounded_line(cr, x0, y0, x1, y1, width)
    cairo_set_line_width(cr, width)
    cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND)
    cairo_move_to(cr, x0, y0)
    cairo_line_to(cr, x1, y1)
    cairo_stroke(cr)
end

function theme.draw_volume(cr, x0, x1, cy, fraction, ix, size, s, fg, active, lit)
    -- A volume slider, in window px: a speaker of width size at ix and a slim track from x0
    -- to x1 drawn like a seek bar, filled to fraction (0 to 1), its knob shown while active
    -- (hovered or dragged). The speaker's body stays in place at every level; to its right,
    -- inside its fixed box, it shows a cross when muted, one wave below half and two from
    -- half up. Shaded at 0.7, full while lit.
    local fx = x0 + (x1 - x0) * math.min(math.max(fraction, 0), 1)
    theme.set(cr, fg, 0.3)                                              -- track
    rounded_line(cr, x0, cy, x1, cy, 4 * s)
    theme.set(cr, fg)                                                   -- level, knob
    if fx > x0 then rounded_line(cr, x0, cy, fx, cy, 4 * s) end
    if active then
        cairo_arc(cr, fx, cy, 5 * s, 0, 2 * math.pi)
        cairo_fill(cr)
    end

    theme.set(cr, fg, lit and 1 or 0.7)
    cairo_new_path(cr)                                                  -- body and cone
    cairo_move_to(cr, ix, cy - 0.17 * size)
    cairo_line_to(cr, ix + 0.22 * size, cy - 0.17 * size)
    cairo_line_to(cr, ix + 0.5 * size, cy - 0.4 * size)
    cairo_line_to(cr, ix + 0.5 * size, cy + 0.4 * size)
    cairo_line_to(cr, ix + 0.22 * size, cy + 0.17 * size)
    cairo_line_to(cr, ix, cy + 0.17 * size)
    cairo_close_path(cr)
    cairo_fill(cr)
    cairo_set_line_width(cr, 1.5 * s)
    cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND)
    local wx = ix + 0.5 * size
    if fraction < 0.005 then                                            -- muted: a cross
        cairo_move_to(cr, ix + 0.64 * size, cy - 0.15 * size)
        cairo_line_to(cr, ix + 0.94 * size, cy + 0.15 * size)
        cairo_move_to(cr, ix + 0.64 * size, cy + 0.15 * size)
        cairo_line_to(cr, ix + 0.94 * size, cy - 0.15 * size)
        cairo_stroke(cr)
    else
        local waves = fraction < 0.5 and {0.2} or {0.2, 0.42}
        for _, r in ipairs(waves) do
            cairo_new_sub_path(cr)
            cairo_arc(cr, wx, cy, r * size, -0.9, 0.9)
            cairo_stroke(cr)
        end
    end
end

-- logical px; logical px right and down; alpha at the card's edge. The blur plus each offset
-- stays within widget_size.py's SHADOW margin (16).
local SHADOW_BLUR, SHADOW_RIGHT, SHADOW_DROP, SHADOW_ALPHA = 7, 5, 4, 0.32

function theme.draw_shadow(cr, x, y, w, h, rad, s)
    -- A soft black shadow around the card, SHADOW_RIGHT to the right and SHADOW_DROP lower,
    -- fading out over SHADOW_BLUR: one rounded rectangle a pixel wider per step, biggest
    -- first, each alpha chosen so the stack reaches SHADOW_ALPHA * (1 - d / blur)^2 at d px
    -- from the card's edge. Clipped to outside the card, so its antialiased edge blends
    -- with the desktop and not with shadow.
    local blur, right, drop = SHADOW_BLUR * s, SHADOW_RIGHT * s, SHADOW_DROP * s
    local function target(d) return SHADOW_ALPHA * (1 - d / blur) ^ 2 end
    cairo_save(cr)
    cairo_rectangle(cr, 0, 0, conky_window.width, conky_window.height)
    theme.rounded_rect(cr, x, y, w, h, rad)
    cairo_set_fill_rule(cr, CAIRO_FILL_RULE_EVEN_ODD)
    cairo_clip(cr)
    cairo_set_fill_rule(cr, CAIRO_FILL_RULE_WINDING)
    for k = blur, 1, -1 do
        local a = 1 - (1 - target(k - 1)) / (1 - target(k))
        local e = k - 1                            -- how far this layer reaches past the card
        theme.rounded_rect(cr, x + right - e, y + drop - e, w + 2 * e, h + 2 * e, rad + e)
        cairo_set_source_rgba(cr, 0, 0, 0, a)
        cairo_fill(cr)
    end
    cairo_restore(cr)
end

return theme
