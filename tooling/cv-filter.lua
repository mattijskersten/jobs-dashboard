-- cv-filter.lua
-- Agents edit only cv.md. This file handles all layout transformations.

local function escape_latex(s)
  return s:gsub("&",  "\\&")
           :gsub("%%", "\\%%")
           :gsub("#",  "\\#")
           :gsub("%$", "\\$")
end

-- Converts "Hello World" → bold small caps LaTeX:
-- \textbf{H}\scalebox{0.8}{\textbf{ELLO}} \textbf{W}\scalebox{0.8}{\textbf{ORLD}}
local function bold_smallcaps(text)
  local result = {}
  for word in text:gmatch("%S+") do
    local first = escape_latex(word:sub(1, 1):upper())
    local rest  = escape_latex(word:sub(2):upper())
    if rest ~= "" then
      table.insert(result,
        "\\textbf{" .. first .. "}\\scalebox{0.8}{\\textbf{" .. rest .. "}}")
    else
      table.insert(result, "\\textbf{" .. first .. "}")
    end
  end
  return table.concat(result, " ")
end

-- Transform name metadata so the template gets pre-formatted LaTeX
function Meta(m)
  if m.name then
    local name_str = pandoc.utils.stringify(m.name)
    m.name = pandoc.MetaInlines{ pandoc.RawInline("latex", bold_smallcaps(name_str)) }
  end
  return m
end

function Header(el)
  if el.level == 2 then
    local text = pandoc.utils.stringify(el)
    return pandoc.RawBlock("latex",
      "\\cvsection{" .. bold_smallcaps(text) .. "}")

  elseif el.level == 3 then
    local text = pandoc.utils.stringify(el)
    local left, right = text:match("^(.+) | (.+)$")
    return pandoc.RawBlock("latex",
      "\\cventry{" .. escape_latex(left) .. "}{" .. escape_latex(right) .. "}")

  elseif el.level == 4 then
    local text = pandoc.utils.stringify(el)
    local left, right = text:match("^(.+) | (.+)$")
    return pandoc.RawBlock("latex",
      "\\cvsubrole{" .. escape_latex(left) .. "}{" .. escape_latex(right) .. "}")
  end
end

-- A paragraph of exactly one Bold span → bold-italic job title
function Para(el)
  if #el.content == 1 and el.content[1].t == "Strong" then
    local text = escape_latex(pandoc.utils.stringify(el.content[1]))
    return pandoc.RawBlock("latex", "\\cvjobtitle{" .. text .. "}")
  end
end

-- ::: summary ... ::: → indented block
function Div(el)
  if el.classes:includes("summary") then
    local result = { pandoc.RawBlock("latex", "\\begin{adjustwidth}{1.5em}{1.5em}") }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, pandoc.RawBlock("latex", "\\end{adjustwidth}"))
    return result
  end

  if el.classes:includes("twocol") then
    local result = { pandoc.RawBlock("latex", "\\begin{multicols}{2}") }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, pandoc.RawBlock("latex", "\\end{multicols}"))
    return result
  end
end
