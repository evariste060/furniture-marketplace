# Approved scope changes

The original requirement documents stay unchanged (see `original-checksums.txt`). Every change
to the MVP scope approved by the project owner after they were written is recorded here, newest
first. Where this file and an original document disagree, this file wins.

## SC-03: social media links in the footer (2026-11-18)

Approved by the project owner on 2026-11-18. Trello card: none.

The footer design showed social icons, but no setting held their links, so they were left out.
The owner added them: administrators set the store's Facebook, Instagram, X, YouTube, TikTok
and LinkedIn links in Settings (each optional, `https://` on the network's own site, removable),
and the footer shows an icon for each link that is set. In the same change the footer's contact
lines were removed and Company moved onto the first row, with "We accept" on a second row.

## SC-02: technical services and service requests (2026-11-17)

Approved by the project owner on 2026-11-17. Trello card: none.

The original documents cover selling electronics only. The owner added **technical services**
(CCTV and security surveillance, smart gates and gate automation, smart automation and access
control, IT infrastructure and networking, phone/computer/electronics repair, technical
training) to the MVP. Services are not products: no price, stock, cart or online payment.

- **Storefront.** A Services page lists the active services as cards; each service has its own
  page with what it includes, who it is for, Call and WhatsApp buttons and a "Request this
  service" form (name, Rwandan mobile number, optional email, location and preferred date,
  client type, message). "Services" is on the category bar after Deals, with a dropdown, and in
  the footer and the mobile menu. Pages exist in English and Kinyarwanda.
- **Home page** (approved the same day): an Our Services section under Featured Products, the
  services in the hero showcase, and Services as the last entry of the All Categories menu with
  the services under it. How Shopping Works is removed, and Best Selling Products and New
  Arrivals move below the category spotlights.
- **Requests.** Each request gets an `SR-` reference and, when an email is given, an
  acknowledgement email. Spam is limited by a hidden honeypot field and a per-number and
  per-network rate limit.
- **Admin.** Administrators and sales staff manage the services (texts in English and
  Kinyarwanda, icon, image, items, order, shown or hidden) and follow requests up (status,
  assignee, internal notes); management can view them. A service with requests can only be
  hidden, not deleted. Every change is audited.

Full specification: `docs/architecture/ADR-013-technical-services.md`.

## SC-01: customer reviews and wishlist move into the MVP (2026-10-27)

Approved by the project owner on 2026-10-27, during frontend phase 2.

The Product Requirements Document lists "customer reviews, wishlist and advanced product
comparison" as out of scope "unless explicitly approved after MVP scope is secured". The owner
approved **customer reviews** and the **wishlist** for the MVP. Product comparison, installment
lending and trade-in stay out of scope.

- **Reviews (backend module 20).** Verified buyers review a product once per delivered order
  item, through a single-use link that expires 90 days after delivery: signed-in customers from
  their order pages, guests from order tracking. Rating 1–5 (required), optional title (at most
  80 characters) and text (at most 2,000), plain text, no photos, no editing after sending. New
  reviews wait for moderation by an administrator or sales staff (`reviews:moderate`); only
  approved reviews are public, with the reviewer's first name and last initial and a "Verified
  purchase" label. Products show the average rating, the number of reviews and the 5-to-1
  distribution; the catalogue filters by minimum rating and sorts by top rated. Sending review
  links by SMS or email waits for notifications (module 17).
- **Wishlist (backend module 21).** Signed-in customers save up to 200 products. A guest who
  taps the heart signs in first, and the product is saved afterwards. Saved products that are
  no longer sold stay in the list, marked "No longer available", so the customer can remove
  them.

Full specification: `docs/IMPLEMENTATION_PLAN.md`, modules 20 and 21.
