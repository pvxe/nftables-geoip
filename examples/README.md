You can try out an example by executing it (probably you will need `sudo`).
Assuming nft is located at `/usr/sbin`.

```
sudo ./example.nft
```

You can specify an additional folder for `nft` to lookup for files with `-I` so you
don't need to modify the includes. This should be the folder in which you saved the
script output.

```
sudo ./example.nft [ -I path/to/script/output ]
```
