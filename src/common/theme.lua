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

function theme.fade_step(bg, target, dt)
    -- one step of the ~1 s fade of bg (changed in place) towards target, and the foreground
    -- for it and the colour drawn on that foreground
    local k = 1 - math.exp(-dt * 3)
    for i = 1, 3 do bg[i] = bg[i] + (target[i] - bg[i]) * k end
    if theme.contrast(theme.LIGHT, bg) >= theme.contrast(theme.DARK, bg) then
        return theme.LIGHT, theme.DARK
    end
    return theme.DARK, theme.LIGHT
end

function theme.rounded_rect(cr, x, y, w, h, rad)
    cairo_new_sub_path(cr)
    cairo_arc(cr, x + w - rad, y + rad, rad, -math.pi / 2, 0)
    cairo_arc(cr, x + w - rad, y + h - rad, rad, 0, math.pi / 2)
    cairo_arc(cr, x + rad, y + h - rad, rad, math.pi / 2, math.pi)
    cairo_arc(cr, x + rad, y + rad, rad, math.pi, 3 * math.pi / 2)
    cairo_close_path(cr)
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
