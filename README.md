# labvault

Lab data management SDK for experimenters.

**Auto-logs notebook execution, stores data with LLM-friendly metadata, and enables AI-powered analysis.**

## Features

- **Zero-effort logging**: Just `exp = lab.new("title")` in a Jupyter Notebook — every cell execution is automatically captured
- **Team data sharing**: All team members' experiments in a single searchable pool
- **LLM-powered analysis**: Search, compare, and analyze experiments via MCP server (Claude, Gemini)
- **Code execution**: LLM generates and runs Python code (fitting, statistics) on your data
- **Local-first**: Data is always saved locally first, then synced — never lost

## Quick Start

```python
from labvault import Lab

lab = Lab("konishi-lab")
exp = lab.new("XRD measurement", sample="Fe-10Cr alloy #42")
exp.add("~/Desktop/xrd_data.ras")
exp.tag("XRD", "Fe-Cr")
exp.results["lattice_a"] = 2.873
```

## Install

```bash
pip install labvault
```

## Architecture

```
labvault (this repo) = Experimenter SDK
labvault-platform    = Backend (MCP server + WebApp + Cloud Functions)
```

## License

MIT
