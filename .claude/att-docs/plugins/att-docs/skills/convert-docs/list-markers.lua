-- Writes the letter or roman numeral Word draws on a list item.
--
-- The output is GitHub-flavored Markdown, and its ordered lists are numbered
-- with digits only, so the writer draws a list Word letters a, b, c as 1, 2, 3.
-- A rule written from the converted document cites the item as Word labels it,
-- "Rule 2.a", and a digit there points at an item the document does not have.
--
-- Each item of a lettered or roman list becomes a bullet whose first line opens
-- with the label Word draws, so the label is in the text. Whatever else the item
-- holds, such as a second paragraph or a list of its own, stays nested under
-- that bullet, where Word draws it. A list numbered with digits is left for the
-- writer to draw, kept apart from a digit list right before it that it does not
-- count on from, so a reader numbers it from its own first number.
--
-- One list is not a list in Word at all. list-numbers.py wraps a paragraph that
-- follows a sub-list and belongs to an item above it in a list of its own, so
-- that the reader nests it under that item, and starts the list at a number
-- past any start Word takes. Such a list is written as the paragraphs it holds.

local List = require 'pandoc.List'

-- The start of a list list-numbers.py made around a paragraph after a sub-list.
-- Word takes a start of 32767 at the most. list-numbers.py holds the same
-- number.
local UNNUMBERED_START = 32768

local ROMAN = {
  {1000, 'm'}, {900, 'cm'}, {500, 'd'}, {400, 'cd'}, {100, 'c'}, {90, 'xc'},
  {50, 'l'}, {40, 'xl'}, {10, 'x'}, {9, 'ix'}, {5, 'v'}, {4, 'iv'}, {1, 'i'},
}

local function roman(number)
  local out = ''
  for _, pair in ipairs(ROMAN) do
    while number >= pair[1] do
      out = out .. pair[2]
      number = number - pair[1]
    end
  end
  return out
end

-- Word letters a list a to z, then aa to zz, then aaa, repeating the letter.
local function letter(number)
  local index = (number - 1) % 26
  local repeats = (number - 1) // 26 + 1
  return string.rep(string.char(string.byte('a') + index), repeats)
end

local LABELS = {
  LowerAlpha = letter,
  UpperAlpha = function(number) return letter(number):upper() end,
  LowerRoman = roman,
  UpperRoman = function(number) return roman(number):upper() end,
}

local function marker(label, delimiter)
  if delimiter == 'OneParen' then
    return label .. ')'
  elseif delimiter == 'TwoParens' then
    return '(' .. label .. ')'
  end
  return label .. '.'
end

-- The bullet items for a lettered or roman list, or nil for any other list.
local function labeled_items(list)
  local attributes = list.listAttributes
  local label = LABELS[attributes.style]
  if label == nil or attributes.start < 1 then
    return nil
  end
  local items = List:new{}
  for index, item in ipairs(list.content) do
    local text = marker(label(attributes.start + index - 1), attributes.delimiter)
    local opening = List:new{pandoc.Str(text)}
    local first = item[1]
    local blocks = List:new{}
    if first ~= nil and (first.t == 'Para' or first.t == 'Plain') then
      if #first.content > 0 then
        opening:insert(pandoc.Space())
        opening:extend(first.content)
      end
      -- The same block kind keeps a tight list tight and a loose one loose.
      blocks:insert(first.t == 'Para' and pandoc.Para(opening) or pandoc.Plain(opening))
      for position = 2, #item do
        blocks:insert(item[position])
      end
    else
      blocks:insert(pandoc.Plain(opening))
      blocks:extend(item)
    end
    items:insert(blocks)
  end
  return items
end

-- The last block written so far, or nil. A paragraph with nothing left in it,
-- as one that held only an image, writes nothing.
local function last_written(out)
  for index = #out, 1, -1 do
    local block = out[index]
    if not ((block.t == 'Para' or block.t == 'Plain') and #block.content == 0) then
      return block
    end
  end
  return nil
end

-- Whether a Markdown reader would give the items of a digit list other numbers
-- than it is written with: a digit list right after another reads as more
-- items of that one, numbered on from its last.
local function renumbered_after(above, list)
  return above ~= nil and above.t == 'OrderedList'
    and list.listAttributes.start ~= above.listAttributes.start + #above.content
end

-- A labeled list joins a bullet list right before or after it, labeled or not.
-- Left as two, the writer puts a blank `&nbsp;` paragraph between them, since
-- Markdown reads two bullet lists in a row as one; the labels already tell the
-- items apart. Two plain bullet lists in a row are left as the writer draws them.
--
-- Markdown reads two digit lists in a row as one list too. The writer's
-- `&nbsp;` paragraph is a space to the stamping step, which takes it out, so
-- where the second list does not count on from the first an empty HTML comment
-- goes between the two: it ends the first list and draws nothing.
function Blocks(blocks)
  local out = List:new{}
  -- The bullet list being gathered: its items, and whether a labeled list is in it.
  local pending, labeled = nil, false
  local function flush()
    if pending ~= nil then
      out:insert(pandoc.BulletList(pending))
      pending, labeled = nil, false
    end
  end
  for _, block in ipairs(blocks) do
    local items = block.t == 'OrderedList' and labeled_items(block) or nil
    if block.t == 'OrderedList' and block.listAttributes.start >= UNNUMBERED_START then
      flush()
      for _, item in ipairs(block.content) do
        out:extend(item)
      end
    elseif items ~= nil then
      pending = pending or List:new{}
      pending:extend(items)
      labeled = true
    elseif block.t == 'BulletList' and pending ~= nil and labeled then
      pending:extend(block.content)
    elseif block.t == 'BulletList' then
      flush()
      pending = List:new(block.content)
    else
      flush()
      if block.t == 'OrderedList' and renumbered_after(last_written(out), block) then
        out:insert(pandoc.RawBlock('html', '<!-- -->'))
      end
      out:insert(block)
    end
  end
  flush()
  return out
end
