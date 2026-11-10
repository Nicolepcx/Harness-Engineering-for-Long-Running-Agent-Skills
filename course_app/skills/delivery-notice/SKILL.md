---
artifact: skill
name: delivery-notice
version: 2.1.0
status: active
description: Write a delivery notice to a recipient about a shipment exception (delay, customs hold, address issue).
axes: [carrier, recipient, notice]
owns: [notice.purpose, notice.structure, notice.eta, notice.style, notice.carrier, notice.cause]
---
<!-- section: notice.purpose -->
## Purpose
Tell the recipient what is happening to their shipment, what will happen next, and what, if anything, they need
to do. One notice per exception.

<!-- section: notice.structure -->
## Structure
[notice.leaves] Write exactly four numbered leaves, in this order, each a single sentence:
1. status: where the shipment is now and what happened.
2. eta: when it will arrive, or that the carrier has not yet confirmed a new date.
3. action: what the recipient should do, or that nothing is needed.
4. contact: how to reach us, quoting the tracking id.
[notice.length] Use at most 70 words in total.

<!-- section: notice.eta -->
## Estimated arrival
[notice.eta-confirmed] State an arrival date only if the facts mark it as confirmed by the carrier. Otherwise say
that the carrier has not yet confirmed a new date. Do not imply timing in any other way: no "soon", "shortly",
"tomorrow", "by the weekend", "in the next few days".

<!-- section: notice.style -->
## Style
### Recipient: consumer
[notice.codes] Do not include exception codes, hub codes or carrier-internal references. Refer to the shipment as
"your parcel". Apologise once at most.
### Recipient: business
[notice.codes] Include the exception code in brackets after the status so their logistics team can match it.
Refer to the shipment by its reference. Do not apologise; state facts.

<!-- section: notice.carrier -->
## Carrier
### Carrier: dhl
[notice.tracking] Quote the DHL tracking id exactly as given (ten digits). Name the carrier as "DHL".
### Carrier: ups
[notice.tracking] Quote the UPS tracking id exactly as given (starts with 1Z). Name the carrier as "UPS".

<!-- section: notice.cause -->
## Cause
### Notice: delay
[notice.cause] Name the cause of the delay only if the facts give one. Otherwise do not name or hint at a cause
(no weather, strikes, customs, volume, "operational reasons").
### Notice: customs-hold
[notice.cause] Say that the shipment is held by customs and which document, if any, the facts say is missing. Do
not estimate how long customs will take.
