export const EXAMPLE_REQUEST =
  "I need a secure web application for my customers. It should handle increasing traffic, protect customer information, and cost as little as possible.";

// Starter descriptions. Words in them (industry, runtime, uploads…) are picked up
// as suggestions for the interview; nothing is confirmed until the user answers.
export const STARTERS: { id: string; label: string; name: string; request: string }[] = [
  { id: "portal", label: "Customer portal", name: "Customer Portal", request: EXAMPLE_REQUEST },
  {
    id: "shop",
    label: "Online store",
    name: "Online Store",
    request:
      "We run an online store for customers across Europe, built with Django. Shoppers upload product photos and we expect Black Friday spikes. We have no dedicated ops team and want to keep costs low.",
  },
  {
    id: "clinic",
    label: "Clinic booking",
    name: "Clinic Booking",
    request:
      "A patient booking system for our clinics in the US, built with Node.js. It stores patient records and documents, must stay available during opening hours, and auditors will review it.",
  },
  {
    id: "internal",
    label: "Internal tool (staging)",
    name: "Ops Dashboard",
    request:
      "A staging environment for an internal dashboard used by employees only during business hours. Python with a small database; it should be as cheap as possible.",
  },
];
