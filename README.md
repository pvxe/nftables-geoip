# Nftables geoip script

Python script that generates .nft files with mappings between IP addresses
and its geolocation, so you can include them inside your rules.

# Requirements

Package used that are not present in the Python Standard Library

- `requests`

# Usage example

To generate ipv4 and ipv6 mappings, download geoip data from db-ip.com
saving the output in the current folder

```
   ./nft_geoip.py --file-location location.csv --download
```

Giving the following output

```
  drwxr-xr-x 2 foobar foobar 4,0K ene  4 19:38 .
  drwxr-xr-x 5 foobar foobar 4,0K ene  4 19:38 ..
  -rw-r--r-- 1 foobar foobar  22M ene  4 19:38 dbip.csv
  -rw-r--r-- 1 foobar foobar  956 ene  4 19:38 geoip-def-africa.nft
  -rw-r--r-- 1 foobar foobar 8,3K ene  4 19:38 geoip-def-all.nft
  -rw-r--r-- 1 foobar foobar  902 ene  4 19:38 geoip-def-americas.nft
  -rw-r--r-- 1 foobar foobar   15 ene  4 19:38 geoip-def-antarctica.nft
  -rw-r--r-- 1 foobar foobar  808 ene  4 19:38 geoip-def-asia.nft
  -rw-r--r-- 1 foobar foobar  810 ene  4 19:38 geoip-def-europe.nft
  -rw-r--r-- 1 foobar foobar  461 ene  4 19:38 geoip-def-oceania.nft
  -rw-r--r-- 1 foobar foobar 8,8M ene  4 19:38 geoip-ipv4.nft
  -rw-r--r-- 1 foobar foobar  16M ene  4 19:38 geoip-ipv6.nft
```

* geoip-def-all defines variables for each country (2-char iso name)
  in location.csv assigning its iso numeric value (eg. Canada, `define $CA = 124`)
* geoip-ipv4.nft defines geoip4 map (@geoip4)
* geoip-ipv6.nft defines geoip6 map (@geoip6)

## Marking packets to its corresponding country

```
  meta mark set ip saddr map @geoip4
```

## Example: Counting incoming Spanish traffic

Create a file, `geoip.nft` (it will be at `/etc/geoip.nft` for this example).
```
  #!/usr/sbin/nft -f

  table geoip {
    include "geoip-def-all.nft"
    include "geoip-ipv4.nft"
    include "geoip-ipv6.nft"

    chain input {
                  type filter hook input priority 0; policy accept;
                  meta mark set ip saddr map @geoip4
                  meta mark $ES counter
    }
  }
```
Then  run ```nft -f /etc/geoip.nft``` to add it to your firewall.

You can also make the new table, chain and rules permanent by editing your distro specific file
(/etc/nftables.conf for Arch Linux or Debian) by including `geoip.nft`. This file is usually run at boot.
```
  #!/usr/sbin/nft -f

  flush ruleset
  include "/etc/geoip.nft"

  # your ruleset...

  ...
```

When updating the geoip maps (`geoip-ipv4` and/or `geoip-ipv6`), you will need to
reload `/etc/geoip.nft` so new geoip maps are included again and old ones dropped:
```
  nft delete table geoip
  nft -f /etc/geoip.nft
```

# Caveats

__It is not possible to use the country definitions inside an interactive
nft shell.__

So, although maps are defined, country definitions do not persist.
You will need to define those geoip rules inside your ruleset definition
files. Like in the example above.

__You will need ~300MB of free memory to run the script and also to load
the full (all) ipv4 and ipv6 maps.__

It's been reported that low memory machines, (eg. GCP f1-micro) are not
enough and the scripts ends up killed by the OOM-killer.

This will be fixed in [#1](https://github.com/JMGuisadoG/nftables-geoip/issues/1).
