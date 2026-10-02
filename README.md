# TomSiegl.github.io

Tom's academic profile website

## Getting started

Requires [Hugo](https://gohugo.io/installation/) (extended edition, v0.166.0 — matching `.github/workflows/hugo.yml`). If `hugo` isn't already on your `PATH`, install the matching binary directly:

```
mkdir -p ~/.local/bin
curl -sL "https://github.com/gohugoio/hugo/releases/download/v0.166.0/hugo_extended_0.166.0_linux-amd64.tar.gz" -o hugo.tar.gz
tar -xzf hugo.tar.gz hugo
mv hugo ~/.local/bin/hugo
rm hugo.tar.gz
export PATH="$HOME/.local/bin:$PATH"
```

No `sudo` required. Add the `export PATH` line to your shell profile (`~/.bashrc`/`~/.zshrc`) to make it permanent.

(swap `linux-amd64` for your platform/architecture from the [releases page](https://github.com/gohugoio/hugo/releases/tag/v0.166.0) if needed.)

Then start the local preview server:

```
hugo server
```

Then open http://localhost:1313/.
