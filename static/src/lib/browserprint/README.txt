Zebra Browser Print SDK — not included
=======================================

This folder is where pos_retail expects Zebra's own "Browser Print" SDK
file to live, so a preset with "Print Directly via Zebra Browser Print"
enabled can find it:

    pos_retail/static/src/lib/browserprint/BrowserPrint-3.x.min.js

It is not bundled with this module because it is Zebra's proprietary,
freely-downloadable file, not something this project can redistribute
sight-unseen. You need to get it yourself, once, per Zebra printer model
family you support:

1. On the till PC (Windows), install Zebra's free "Browser Print"
   application, downloaded from Zebra's own support/downloads site
   (search "Zebra Browser Print" on zebra.com). This installs a small
   background app that exposes locally-connected Zebra printers to any
   webpage running in the browser on that same PC.

2. From the same download (or from Zebra's Browser Print SDK page), take
   the JavaScript file usually named "BrowserPrint-3.x.min.js" (exact
   version number varies) and save it here as exactly:

       BrowserPrint-3.x.min.js

3. Re-open the label print page (POS "Print Barcode Label" popup, or the
   backend thermal label wizard). If the file is present and the Browser
   Print app is running with the Zebra ZD410 as its default printer,
   labels print directly with no dialog. If either is missing, printing
   falls back automatically to the normal browser print dialog — nothing
   breaks either way.

You only need to install the Browser Print app once per till machine.
For the JS file: since this project deploys to the server with a plain
"git pull" (see the deployment notes elsewhere in this repo), it's
simplest to commit the file here once you've placed it, rather than
copying it to the server by hand on every deploy.
