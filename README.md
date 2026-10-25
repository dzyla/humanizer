# humanizer

A local, two-panel web UI for the [humanizer](https://github.com/sgaofen/humanizer-local-model) rewrite model on Linux/WSL, with a grammar check so the rewrite is not only human-sounding but also correct.

- **Draft on the left, rewrite on the right.** New wording is highlighted and replaced wording is struck through. Long drafts are rewritten piece by piece and fill in as they finish.
- **The `hz` pipeline underneath.** Headings, code, tables and links are kept as they are. A piece is rewritten again if a number or link goes missing, it copies too much of the draft, or it comes back cut off.
- **Grammar check with [LanguageTool](https://languagetool.org), running locally.** Your text never leaves the machine.
  - Fixed automatically (toggle **Auto-correct**): grammar, punctuation, capitalization, doubled words, a/an, and prose lines that end without punctuation.
  - Names restored from the draft: if the model writes `genbank`, `snapgene` or `orf`, the draft's `GenBank`, `SnapGene` and `ORF` come back.
  - Only underlined, never auto-applied: spelling and style. Click an underline to apply a suggestion or ignore it. Every word in your draft and every word in `ui/science-words.txt` counts as correctly spelled.
  - The list under the rewrite shows each auto-correction so you can review it.
- Import `.txt`, `.md` or `.docx`; copy or download the rewrite; scroll both panels together.

LanguageTool catches agreement (`results was`), `less`/`fewer`, doubled words, a/an, `neither … or` and capitalization. It does **not** catch sentence fragments, comma splices or most missing articles, so still read the result.

## Setup

Needs Python 3.8+, [llama.cpp](https://github.com/ggml-org/llama.cpp) (`llama-server`), a GPU with about 10 GB free for the Q4_K_M model, and Java 17+ for the grammar check.

```bash
git clone https://github.com/dzyla/humanizer && cd humanizer
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# model weights (7.6 GB) and prompt format, from https://huggingface.co/jialinyyzz/humanizer
mkdir -p humanizer-model
for f in humanizer-12b-Q4_K_M.gguf prompt_format.json; do
  curl -L -o humanizer-model/$f https://huggingface.co/jialinyyzz/humanizer/resolve/main/$f
done

./setup-languagetool.sh          # optional: grammar check (~250 MB into tools/)
```

If `llama-server` is not on your `PATH`, set `LLAMA_SERVER=/path/to/llama-server`.

## Use

```bash
./humanize-ui.sh                 # starts the model server and LanguageTool if needed, then the UI
```

Open <http://127.0.0.1:8086>. Ctrl+Enter rewrites.

Command line, without the UI:

```bash
./humanize.sh draft.md -o draft.out.md
./humanize.sh report.docx -o report.out.docx
```

| Script | What it starts | Port |
|---|---|---|
| `start-server.sh` | llama-server with the model | 8085 (`HUMANIZER_PORT`) |
| `start-languagetool.sh` | LanguageTool | 8081 (`LANGUAGETOOL_PORT`) |
| `humanize-ui.sh` | both of the above if needed, then the UI | 8086 (`HUMANIZER_UI_PORT`) |

Other settings:
- `HUMANIZER_MODEL`: another GGUF file.
- `HUMANIZER_CTX`: context size, default 4096.
- `LANGUAGETOOL_LANG`: language, default `auto`.
- `LANGUAGETOOL_VARIANT`: `en-US` (default) or `en-GB` spelling.

## Credits

- Model and `hz` pipeline: [sgaofen/humanizer-local-model](https://github.com/sgaofen/humanizer-local-model) (Apache-2.0), weights at [jialinyyzz/humanizer](https://huggingface.co/jialinyyzz/humanizer).
- Grammar check: [LanguageTool](https://github.com/languagetool-org/languagetool) (LGPL-2.1), downloaded by `setup-languagetool.sh` and not included in this repository.
