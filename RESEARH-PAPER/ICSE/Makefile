# ICSE 2027 paper build
# Targets:
#   make          build main.pdf (default)
#   make quick    one pdflatex pass (no bib refresh; use during section edits)
#   make clean    remove all intermediate files
#   make veryclean   also remove main.pdf

PAPER = main
TEX = $(PAPER).tex
PDF = $(PAPER).pdf

LATEX = pdflatex -interaction=nonstopmode -halt-on-error
BIBTEX = bibtex

SECTIONS = $(wildcard sections/*.tex)
BIB = references.bib

.PHONY: all quick clean veryclean

all: $(PDF)

$(PDF): $(TEX) $(SECTIONS) $(BIB)
	$(LATEX) $(PAPER)
	-$(BIBTEX) $(PAPER)
	$(LATEX) $(PAPER)
	$(LATEX) $(PAPER)

quick: $(TEX) $(SECTIONS)
	$(LATEX) $(PAPER)

clean:
	rm -f *.aux *.log *.bbl *.blg *.toc *.out *.lof *.lot *.fls *.fdb_latexmk *.synctex.gz
	rm -f sections/*.aux

veryclean: clean
	rm -f $(PDF)
