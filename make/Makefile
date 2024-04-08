.SUFFIXES:

A: B1 B2 B3 B4
	echo "Doing $@"

B%: C%
	echo "Doing $@"

C%:
	echo "Doing $@"

# testing task failures:
C5:
	echo "Failing $@" && exit 1
