# Recipies for stuff
export PYTHONPATH := .

all:	docs alltests dev web compilemessages

dev:
	@echo export PYTHONPATH=`pwd`

arch-dev:
	sudo pacman -Syu community/python2-pillow extra/python2-lxml community/python2-jinja \
	                 community/python2-pep8 extra/python2-nose community/phantomjs \
	                 extra/python2-pip community/python2-mock \
	                 extra/ruby
	yaourt yuicompressor
	yaourt spambayes 
	sudo pip2 install 'selenium>=2.40.0'
	which lessc >/dev/null || sudo gem install therubyracer less

debian-dev:
	sudo apt-get install python-imaging python-lxml python-jinja2 pep8 \
	                     ruby-dev yui-compressor python-nose spambayes \
	                     phantomjs python-pip python-mock
	if [ "$(shell cat /etc/debian_version)" = "jessie/sid"  ]; then\
		 sudo apt-get install rubygems-integration;\
	else \
		sudo apt-get install rubygems; \
	fi
	sudo pip install 'selenium>=2.40.0'
	which lessc >/dev/null || sudo gem install therubyracer less

docs:
	@test -d doc || \
           git submodule update --remote
	@python2 mailpile/urlmap.py |grep -v ^FIXME: >doc/URLS.md
	@ls -l doc/URLS.md
	@python2 mailpile/defaults.py |grep -v -e ^FIXME -e ';timestamp' \
           >doc/defaults.cfg
	@ls -l doc/defaults.cfg

web: less js
	@true

alltests: clean docs
	@python2 mailpile/mailutils.py
	@python2 mailpile/config.py
	@python2 mailpile/util.py
	@python2 mailpile/vcard.py
	@python2 mailpile/workers.py
	@python2 mailpile/mail_source/imap.py
	@chmod go-rwx testing/gpg-keyring
	@python2 scripts/mailpile-test.py
	@nosetests

clean:
	@rm -f *.pyc */*.pyc */*/*.pyc mailpile-tmp.py mailpile.py
	@rm -f .appver MANIFEST setup.cfg .SELF .*deps
	@rm -f scripts/less-compiler.mk
	@rm -rf *.egg-info build/ mp-virtualenv/ dist/ testing/tmp/

virtualenv:
	virtualenv -p python2 mp-virtualenv
	bash -c 'source mp-virtualenv/bin/activate && pip install -r requirements.txt && python setup.py install'

js:
	@cat static/default/js/mailpile.js > static/default/js/mailpile-min.js
	@cat `find static/default/js/app/ -name "*.js"` >> static/default/js/mailpile-min.js

less: less-compiler
	@make -s -f scripts/less-compiler.mk

less-loop: less-compiler
	@echo 'Running less compiler every 15 seconds. CTRL+C quits.'
	@while [ 1 ]; do \
                make -s less; \
                sleep 15; \
        done

less-compiler:
	@cp scripts/less-compiler.in scripts/less-compiler.mk
	@find static/default/less/ -name '*.less' \
                |perl -npe s'/^/\t/' \
		|perl -npe 's/$$/\\/' \
                >>scripts/less-compiler.mk
	@echo >> scripts/less-compiler.mk
	@perl -e 'print "\t\@touch .less-deps", $/' >> scripts/less-compiler.mk

genmessages:
	@scripts/make-messages.sh

compilemessages:
	@scripts/compile-messages.sh
