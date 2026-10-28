-- Cairo drawing for the speech widget, fed by speechqueue.py:
--   draw.txt      geometry (logical px, from the card's top left); its scale line is the
--                 display's scale and the text scale, its shadow line the margin round the card
--   widget.txt    conky's markup, which conky.conf shows through conky_widget
require 'cairo'
pcall(require, 'cairo_xlib')

-- The shared drawing helpers sit in ../common, installed or in a checkout.
local here = debug.getinfo(1, 'S').source:match('^@(.*)/[^/]*$')
    or (os.getenv('CSN_DIR') or '/usr/share/conky-spotify-nowplaying') .. '/speech'
package.path = here .. '/../common/?.lua;' .. package.path
local theme = require 'theme'

local cache = os.getenv('HOME') .. '/.cache/conky-widgets/speech/'
local bg = {0.094, 0.094, 0.094}          -- Spotify's #181818
local fg = theme.LIGHT
local margin = 0

local function read(name)
    local f = io.open(cache .. name)
    if not f then return nil end
    local s = f:read('*a')
    f:close()
    return s
end

local function load_draw()
    local d = {}
    for line in (read('draw.txt') or ''):gmatch('[^\n]+') do
        local key, rest = line:match('^(%S+)%s+(.*)$')
        if key then
            local t = {}
            for v in rest:gmatch('%S+') do t[#t + 1] = tonumber(v) or v end
            d[key] = t
        end
    end
    return d
end

local function with_cairo(fn)
    local cs = cairo_xlib_surface_create(conky_window.display, conky_window.drawable,
                                         conky_window.visual, conky_window.width, conky_window.height)
    local cr = cairo_create(cs)
    fn(cr)
    cairo_destroy(cr)
    cairo_surface_destroy(cs)
end

function conky_mouse(event)
    return false
end

function conky_widget()
    return read('widget.txt') or ''
end

function conky_fg(which)
    local c = which == 'title' and fg or theme.secondary(fg, bg)
    return string.format('${color %02x%02x%02x}', math.floor(c[1] * 255 + 0.5),
                         math.floor(c[2] * 255 + 0.5), math.floor(c[3] * 255 + 0.5))
end

function conky_draw_background()
    -- the card, inset by the shadow margin draw.txt gives, and its shadow in that margin
    if conky_window == nil then return end
    local d = load_draw()
    local s = d.scale and d.scale[1] or 1
    margin = (d.shadow and d.shadow[1] or 0) * s
    local w, h = conky_window.width - 2 * margin, conky_window.height - 2 * margin
    if w <= 0 or h <= 0 then margin, w, h = 0, conky_window.width, conky_window.height end
    local rad = math.min(24, h / 4)
    with_cairo(function(cr)
        if margin > 0 then theme.draw_shadow(cr, margin, margin, w, h, rad, s) end
        theme.rounded_rect(cr, margin, margin, w, h, rad)
        cairo_set_source_rgb(cr, bg[1], bg[2], bg[3])
        cairo_fill(cr)
    end)
end

function conky_draw_widget()
end
