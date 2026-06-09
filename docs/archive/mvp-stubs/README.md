# Archived MVP Stubs

These files are kept as historical reference only.

They are not imported by the current harness runtime and are not packaged into the Docker image:

- `prompts/`: early static prompt drafts. Current agents build deterministic artifacts from Python code.
- `sandbox/`: placeholder Docker sandbox interface. Current agent runners execute through local, scoped runner code.
- `mcp/`: placeholder MCP tool layer. Current integrations use concrete service adapters.

If one of these surfaces becomes real runtime behavior again, move it back into a first-class package and add tests that import it directly.
