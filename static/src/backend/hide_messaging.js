/** @odoo-module **/

import { registry } from "@web/core/registry";

// Drop the messaging bubble from the top bar. It opens the same outward
// "send message" composer that was removed from the chatter, so it goes too;
// the Activity bell (a separate systray item) stays. Done inside a service so
// it runs only after every module -- including mail -- has registered its
// systray items; removing at module-load time would race mail's own add().
const posRetailHideMessagingService = {
    start() {
        const systray = registry.category("systray");
        if (systray.contains("mail.messaging_menu")) {
            systray.remove("mail.messaging_menu");
        }
    },
};

registry.category("services").add("pos_retail_hide_messaging", posRetailHideMessagingService);
