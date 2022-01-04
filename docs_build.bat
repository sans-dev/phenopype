@echo off
@echo .doctrees > docs/.gitignore

if "%*"=="-t" (
	rmdir /Q /S _temp
)

if "%*"=="-d" (
	rmdir /Q /S docs
)

if "%*"=="-D" (
	rmdir /Q /S docs _temp
)

sphinx-multibuild -c docs_source -i docs_source -i ../phenopype-tutorials  -s _temp/docs -o docs -a -b dirhtml

robocopy docs_source docs README.md

if "%*"=="-o" (
	cd docs
	rmdir ".git" /S /Q
	git init
	@echo .doctrees > .gitignore
	git add .
	git commit -m "- auto-generated with sphinx -"
	git remote add origin https://github.com/phenopype/static-phenopype-docs
	git push --force origin main
	cd ..
)
