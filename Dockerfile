# Self-hosted image, so LuaLaTeX can never be taken away by someone else's
# base image.
#
# WHY THIS EXISTS: Streamlit Community Cloud installs packages.txt with apt
# against an image whose sources still list Debian bullseye. bullseye went
# oldoldstable and its security Release file expired 2026-09-07 21:13:04 UTC,
# so `apt-get update` returns non-zero and every deploy with a packages.txt
# fails - taking the whole app down, not just PDF export. See
# PACKAGES_DISABLED.md. Nothing in this repo could fix that, because the broken
# apt source was not in this repo.
#
# bookworm (Debian 12) is pinned deliberately: it is the current oldstable with
# security support, which is exactly the property bullseye lost. Revisit before
# its own EOL rather than after.
FROM python:3.12-slim-bookworm

# The same three TeX Live packages packages.txt asked for, plus plain-generic.
# Checked against what main.tex / elsa_main.tex / cover_letter.tex \usepackage:
#   texlive-luatex          fontspec, luacode  (the templates are LuaLaTeX-only)
#   texlive-latex-extra     enumitem, titlesec, fullpage, multirow
#   texlive-fonts-extra     newtxtext/newtxmath, marvosym
#   texlive-plain-generic   binhex.tex, pulled in by newtx
#   texlive-xetex           realscripts.sty, also pulled in by newtx. The name
#                           is misleading and the package is easy to "clean up"
#                           as obviously unnecessary for a LuaLaTeX-only app -
#                           it is not. Without it both templates die at
#                           newtxtext's \ifntx@KOMA branch.
# fonts-extra is the bulk of the image. It stays because newtx is the templates'
# body font: dropping it does not shrink the image so much as change what the
# resume looks like.
#
# NO --no-install-recommends, deliberately, and this is not an oversight to be
# tidied up later. TeX packaging leans on Recommends for the .sty files a
# package's own macros \input at run time, and Debian's texlive-* packages do
# not declare those as hard Depends. Building with the flag produced an image
# that installed cleanly and then failed at compile time on a chain of missing
# files - binhex.tex, then realscripts.sty, then more behind those. Streamlit
# Cloud installed packages.txt with recommends, which is why the same three
# package names worked there. Verified by compiling both real templates in the
# built image; see DEPLOY.md.
RUN apt-get update && apt-get install -y \
        texlive-luatex \
        texlive-latex-extra \
        texlive-fonts-extra \
        texlive-plain-generic \
        texlive-xetex \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so an app-code edit does not reinstall them.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects PORT; 8080 is its default and a sane local fallback.
ENV PORT=8080
EXPOSE 8080

# No shell form with $PORT expansion in exec form, so this goes through sh -c.
# --server.headless stops Streamlit trying to open a browser and prompting for
# an email on first run, which would block startup in a container.
CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true"]
