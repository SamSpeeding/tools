GO ?= go
R3P_BINARY ?= $(CURDIR)/r3p-service
R3P_CA_BUNDLE ?= /etc/ssl/certs/ca-certificates.crt

.PHONY: all clean romfs
all:
ifeq ($(R3P_BINARY),$(CURDIR)/r3p-service)
	CGO_ENABLED=0 GOOS=linux GOARCH=mipsle GOMIPS=softfloat $(GO) build -trimpath -ldflags="-s -w" -o $(R3P_BINARY) .
endif

romfs: all
	$(ROMFSINST) -S $(R3P_BINARY) /usr/sbin/r3p-service
	$(ROMFSINST) -d -S $(R3P_CA_BUNDLE) /etc_ro/ssl/certs/ca-certificates.crt

clean:
	rm -f r3p-service
