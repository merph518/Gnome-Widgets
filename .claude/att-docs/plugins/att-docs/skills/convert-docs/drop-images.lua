-- Removes the nodes that cannot survive the trip to plain Markdown.
--
-- Images go because the output is Markdown only, with no media extraction and
-- no _assets folder, so an image node would render as a link to a file that is
-- never written. Each picture leaves a plain-text placeholder where it was, so
-- the text still says a picture was there: [picture] inside a line of text, and
-- [Picture] for a picture alone in its paragraph, such as a screen print. These
-- specifications quote an icon or a column header by putting its picture between
-- quote marks, and without the placeholder the sentence reads 'the '' icon'.
-- The picture's alt text follows a colon when the document gives one. The
-- placeholder is never a link, and the Markdown writer escapes its brackets.
--
-- A Figure keeps its caption text as an ordinary paragraph under the
-- placeholder, and keeps any other text it holds.
--
-- Spans and divs go because Markdown has nothing to render them as. A Word
-- highlight or character style arrives as a Span, and left alone the writer
-- emits it as a raw <span class="mark"> that is neither Markdown nor anything
-- the reader needs. Unwrapping keeps the text and drops the wrapper. Doing it
-- here rather than over the finished text is what keeps the documents' own
-- angle brackets intact: these specifications write their placeholders as
-- <First Name> and quote XML payloads verbatim.
--
-- The filter runs in three passes, in order: figures, then paragraphs that
-- hold only pictures, then everything else. Pandoc runs a pass's inline
-- functions before its block functions, so a paragraph that held only a
-- picture can be told apart only before the picture turns into text.

local INLINE, BLOCK = 'picture', 'Picture'

-- Word writes alt text of its own for a picture nobody described, such as
-- "A screenshot of a computer / Description automatically generated" or, in
-- newer versions, "... / AI-generated content may be incorrect." It says
-- nothing the placeholder does not, so it is left out.
local MACHINE_ALT = {
  'description automatically generated',
  'ai-generated content may be incorrect',
}

-- Nodes that wrap a picture without adding any text of their own. A Quoted
-- node is not one: its quote marks are text, and a quoted picture is a picture
-- inside a sentence.
local HOLDERS = {
  Span = true, Link = true, Emph = true, Strong = true, Strikeout = true,
  Superscript = true, Subscript = true, Underline = true, SmallCaps = true,
}

local function alt_text(image)
  local alt = pandoc.utils.stringify(image.caption or {})
  alt = alt:gsub('%s+', ' '):gsub('^ ', ''):gsub(' $', '')
  if alt == '' then
    return nil
  end
  local lower = alt:lower()
  for _, phrase in ipairs(MACHINE_ALT) do
    if lower:find(phrase, 1, true) then
      return nil
    end
  end
  return alt
end

-- The placeholder for one picture, as Str and Space nodes. The alt text is
-- read only when `image` is given.
local function placeholder(word, image)
  local alt = image and alt_text(image)
  return pandoc.Inlines('[' .. word .. (alt and (': ' .. alt) or '') .. ']')
end

-- The pictures in `inlines` when it holds pictures and nothing else but
-- spaces and wrappers, or nil.
local function only_pictures(inlines, found)
  for _, node in ipairs(inlines) do
    if node.t == 'Image' then
      found:insert(node)
    elseif node.t == 'Space' or node.t == 'SoftBreak' or node.t == 'LineBreak' then
      -- nothing to read
    elseif HOLDERS[node.t] then
      if not only_pictures(node.content, found) then
        return nil
      end
    else
      return nil
    end
  end
  return found
end

local function pictures_in(inlines)
  local found = only_pictures(inlines, pandoc.List())
  if found and #found > 0 then
    return found
  end
  return nil
end

-- One [Picture] per picture, on one line. A figure's caption names its
-- picture, so a figure leaves the alt text out.
local function picture_line(pictures, with_alt)
  local line = pandoc.Inlines{}
  for index, image in ipairs(pictures) do
    if index > 1 then
      line:insert(pandoc.Space())
    end
    line:extend(placeholder(BLOCK, with_alt and image or nil))
  end
  return line
end

local figures = {
  Figure = function(fig)
    local out = pandoc.Blocks{}
    for _, block in ipairs(fig.content) do
      local pictures = (block.t == 'Para' or block.t == 'Plain') and pictures_in(block.content)
      if pictures then
        out:insert(pandoc.Para(picture_line(pictures, false)))
      elseif block.t == 'Plain' then
        out:insert(pandoc.Para(block.content))
      else
        out:insert(block)
      end
    end
    if fig.caption and fig.caption.long then
      out:extend(fig.caption.long)
    end
    return out
  end,
}

-- A paragraph that holds only pictures, as a line of [Picture] placeholders.
local function picture_block(block)
  local pictures = pictures_in(block.content)
  if pictures then
    block.content = picture_line(pictures, true)
    return block
  end
end

local alone = {
  -- A link around nothing but a picture would leave the placeholder as the
  -- link's text, and the placeholder is never a link.
  Link = function(link)
    if pictures_in(link.content) then
      return link.content
    end
  end,

  Para = function(block)
    return picture_block(block)
  end,

  Plain = function(block)
    return picture_block(block)
  end,
}

-- A space at the front of a paragraph goes. The reader trims the space a
-- paragraph opens with, but not one that sits behind a bookmark, and once the
-- bookmark's span is unwrapped that space is first. Markdown draws no space
-- there, and the writer sets a space that opens a list item after the item's
-- number, which moves the item's text a column past the indent of the lists
-- under it: a reader then takes those lists for code.
local WRAPPERS = {
  Emph = true, Strong = true, Strikeout = true, Superscript = true, Subscript = true,
}

local function without_leading_space(inlines)
  while #inlines > 0 do
    local first = inlines[1]
    if first.t == 'Space' or first.t == 'SoftBreak' then
      inlines:remove(1)
    elseif WRAPPERS[first.t] then
      local content = without_leading_space(first.content)
      if #content > 0 then
        first.content = content
        inlines[1] = first
        return inlines
      end
      inlines:remove(1)
    else
      return inlines
    end
  end
  return inlines
end

local rest = {
  Image = function(image)
    return placeholder(INLINE, image)
  end,

  Span = function(span)
    return span.content
  end,

  Div = function(div)
    return div.content
  end,

  -- Underline and small caps are their own node types rather than spans, and
  -- Markdown can write neither, so the writer falls back to a raw
  -- <span class="underline"> for them. The formatting is Word's and the words
  -- are the document's, so the wrapper goes and the text stays.
  Underline = function(node)
    return node.content
  end,

  SmallCaps = function(node)
    return node.content
  end,

  Para = function(block)
    block.content = without_leading_space(block.content)
    return block
  end,

  Plain = function(block)
    block.content = without_leading_space(block.content)
    return block
  end,
}

return { figures, alone, rest }
