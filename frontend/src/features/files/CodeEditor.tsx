import { closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete'
import { defaultKeymap, history, historyKeymap, indentLess, indentMore, indentWithTab, redo, undo } from '@codemirror/commands'
import { bracketMatching, HighlightStyle, indentOnInput, StreamLanguage, syntaxHighlighting } from '@codemirror/language'
import { openSearchPanel, search, searchKeymap } from '@codemirror/search'
import { Compartment, EditorState } from '@codemirror/state'
import type { Extension } from '@codemirror/state'
import { drawSelection, EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from '@codemirror/view'
import { tags } from '@lezer/highlight'
import { Braces, IndentDecrease, IndentIncrease, Redo2, Search, Undo2, WrapText } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/button'

const night = EditorView.theme({
  '&': { backgroundColor: '#121621', color: '#c5cce4', height: '100%' },
  '.cm-content': { caretColor: '#c0a6ff', padding: '11px 0', lineHeight: '1.65' },
  '.cm-line': { padding: '0 10px' },
  '.cm-scroller': { fontFamily: 'var(--font-mono)', fontSize: '13px', overflow: 'auto' },
  '.cm-gutters': { backgroundColor: '#131824', color: '#69778c', borderRight: '1px solid #242b3a' },
  '.cm-activeLine': { backgroundColor: '#1b2131' },
  '.cm-activeLineGutter': { backgroundColor: '#21283a', color: '#aab9cf' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': { background: '#413565' },
  '.cm-matchingBracket': { background: '#3b3457', color: '#d8c6fc', outline: '1px solid #65588a' },
  '.cm-panels': { background: '#1a2030', color: '#e6edf3' },
  '.cm-panel.cm-search': { padding: '8px', lineHeight: '2.4', whiteSpace: 'normal' },
  '.cm-panel.cm-search label': { whiteSpace: 'nowrap' },
  '.cm-panel.cm-search input, .cm-panel.cm-search button': { borderRadius: '4px', padding: '2px 5px', maxWidth: '52%' },
  '.cm-panel.cm-search [name=close]': { top: '5px', right: '5px', fontSize: '20px' },
  '.cm-panel.cm-search button': { background: '#262e42', color: '#e6edf3', border: '1px solid #3a4257' },
  '@media (max-width: 640px)': { '.cm-scroller': { fontSize: '16px' } },
}, { dark: true })

const syntax = syntaxHighlighting(HighlightStyle.define([
  { tag: [tags.keyword, tags.modifier], color: '#bb9af7' },
  { tag: [tags.comment, tags.meta], color: '#8090ad', fontStyle: 'italic' },
  { tag: [tags.string, tags.special(tags.string)], color: '#a9d283' },
  { tag: [tags.number, tags.bool, tags.null], color: '#ff9e64' },
  { tag: [tags.definition(tags.name), tags.function(tags.variableName), tags.heading], color: '#82aaff' },
  { tag: [tags.propertyName, tags.attributeName, tags.typeName], color: '#7dcfff' },
  { tag: [tags.operator, tags.punctuation], color: '#a9b7d0' },
  { tag: tags.tagName, color: '#f7768e' },
]))

async function parseLanguage(language: string): Promise<Extension> {
  switch (language) {
    case 'python': return (await import('@codemirror/lang-python')).python()
    case 'javascript':
    case 'jsx':
    case 'typescript':
    case 'tsx':
      return (await import('@codemirror/lang-javascript')).javascript({
        typescript: language === 'typescript' || language === 'tsx',
        jsx: language === 'jsx' || language === 'tsx',
      })
    case 'json': return (await import('@codemirror/lang-json')).json()
    case 'yaml': return (await import('@codemirror/lang-yaml')).yaml()
    case 'html': return (await import('@codemirror/lang-html')).html()
    case 'css': return (await import('@codemirror/lang-css')).css()
    case 'bash': return StreamLanguage.define((await import('@codemirror/legacy-modes/mode/shell')).shell)
    case 'toml': return StreamLanguage.define((await import('@codemirror/legacy-modes/mode/toml')).toml)
    case 'markdown': return (await import('@codemirror/lang-markdown')).markdown()
    case 'sql': return (await import('@codemirror/lang-sql')).sql()
    default: return []
  }
}

function sourceFormat(value: string) {
  const endings = [...new Set(value.match(/\r\n|\r|\n/g) ?? [])]
  const separator = endings[0] ?? '\n'
  return { separator, mixed: endings.length > 1 }
}

export default function CodeEditor({ initial, language, name, active, onEdit, onSave }: {
  initial: string; language: string; name: string; active: boolean; onEdit: (text: string) => void; onSave: () => void;
}) {
  const element = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const callbacks = useRef({ onEdit, onSave })
  const [wrap, setWrap] = useState(false)
  const [wrapping] = useState(() => new Compartment())
  const [syntaxFailed, setSyntaxFailed] = useState(false)
  const [{ separator, mixed }] = useState(() => sourceFormat(initial))
  const [mountedInitial] = useState(initial)
  useEffect(() => { callbacks.current = { onEdit, onSave } }, [onEdit, onSave])
  useEffect(() => {
    const languageCompartment = new Compartment()
    const editor = new EditorView({
      parent: element.current!,
      state: EditorState.create({
        doc: mountedInitial.replace(/\r\n|\r|\n/g, separator),
        extensions: [
          EditorState.lineSeparator.of(separator), EditorState.tabSize.of(4),
          EditorView.contentAttributes.of({ 'aria-label': `Edit ${name}`, spellcheck: 'false', autocapitalize: 'off' }),
          lineNumbers(), highlightActiveLine(), highlightActiveLineGutter(), drawSelection(), search({ top: true }),
          history(), indentOnInput(), bracketMatching(), closeBrackets(), night, syntax,
          languageCompartment.of([]), wrapping.of([]),
          keymap.of([
            { key: 'Mod-s', preventDefault: true, run: () => { callbacks.current.onSave(); return true } },
            ...closeBracketsKeymap, ...defaultKeymap, ...historyKeymap, ...searchKeymap, indentWithTab,
          ]),
          EditorView.updateListener.of(update => {
            if (update.docChanged) callbacks.current.onEdit(update.state.sliceDoc())
          }),
        ],
      }),
    })
    view.current = editor
    void parseLanguage(language).then(extension => {
      if (view.current === editor) editor.dispatch({ effects: languageCompartment.reconfigure(extension) })
    }).catch(() => { if (view.current === editor) setSyntaxFailed(true) })
    return () => { editor.destroy(); view.current = null }
  }, [language, mountedInitial, name, separator, wrapping])

  useEffect(() => {
    if (active) view.current?.requestMeasure()
  }, [active])

  function run(command: (editor: EditorView) => unknown) {
    if (view.current) {
      view.current.focus()
      command(view.current)
    }
  }

  function toggleWrap() {
    const next = !wrap
    setWrap(next)
    view.current?.dispatch({ effects: wrapping.reconfigure(next ? EditorView.lineWrapping : []) })
  }

  const insert = (placed: string, close = '') => run(editor => {
    const selected = editor.state.sliceDoc(editor.state.selection.main.from, editor.state.selection.main.to)
    const from = editor.state.selection.main.from
    editor.dispatch({
      changes: { from, to: editor.state.selection.main.to, insert: placed + selected + close },
      selection: { anchor: from + placed.length + selected.length },
    })
  })

  return <div className="editor-body" hidden={!active}>
    {syntaxFailed && <div className="connection-notice editor-note">Syntax highlighting could not load. Editing remains available.</div>}
    {mixed && <div className="connection-notice editor-note">Editing this file normalizes its mixed line endings.</div>}
    <div className="editor-toolbar" role="group" aria-label="Editor commands">
      <Button variant="ghost" size="icon" aria-label="Undo" onClick={() => run(undo)}><Undo2 size={17}/></Button>
      <Button variant="ghost" size="icon" aria-label="Redo" onClick={() => run(redo)}><Redo2 size={17}/></Button>
      <span className="tool-separator"/>
      <Button variant="ghost" size="small" onClick={() => insert('\t')}>Tab</Button>
      <Button variant="ghost" size="icon" aria-label="Decrease indentation" onClick={() => run(indentLess)}><IndentDecrease size={17}/></Button>
      <Button variant="ghost" size="icon" aria-label="Increase indentation" onClick={() => run(indentMore)}><IndentIncrease size={17}/></Button>
      <Button variant="ghost" size="icon" aria-label="Insert braces" onClick={() => insert('{', '}')}><Braces size={17}/></Button>
      <Button variant="ghost" size="small" className="mono" aria-label="Insert parentheses" onClick={() => insert('(', ')')}>( )</Button>
      <Button variant="ghost" size="small" className="mono" aria-label="Insert square brackets" onClick={() => insert('[', ']')}>[ ]</Button>
      <span className="tool-separator"/>
      <Button variant="ghost" size="icon" aria-label="Search and replace" onClick={() => run(openSearchPanel)}><Search size={17}/></Button>
      <Button variant="ghost" size="icon" aria-label="Word wrap" aria-pressed={wrap} onClick={toggleWrap}><WrapText size={17}/></Button>
    </div>
    <div className="editor-container" ref={element}/>
  </div>
}
