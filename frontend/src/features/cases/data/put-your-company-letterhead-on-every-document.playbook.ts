// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Put your company logo and letterhead on every document".
//
// Universal: every firm that sends RFIs, payment applications, transmittals
// and closeout papers to an owner, architect or lender is expected to send
// them on its own letterhead. The office sets the logos, the company details
// and the page layout once in Settings, checks the server's sample PDF, and
// then sees a live RFI and the other formal documents print the same way.
// The step wording follows the labels on the Company & documents tab. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "put-your-company-letterhead-on-every-document",
  order: 346,
  category: "commercial",
  // A one-time office setup that belongs before the first document goes out,
  // not in the build stage the commercial discipline would imply.
  stage: "define",
  companyTypes: ["general-contractor", "subcontractor", "project-manager", "designer", "cost-consultant"],
  roles: ["document-controller", "project-manager", "contract-administrator"],
  icon: "Stamp",
  titleKey: "cases.put_your_company_letterhead_on_every_document.title",
  titleDefault: "Put your company logo and letterhead on every document",
  descKey: "cases.put_your_company_letterhead_on_every_document.desc",
  descDefault:
    "Set your logos, legal name, address and registration numbers once, check the sample PDF, and every RFI, payment application, transmittal and closeout document you send to an owner, architect or lender goes out on your company letterhead.",
  estMinutes: 10,
  steps: [
    {
      id: "logos",
      icon: "Upload",
      inputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.logos.in.formal", label: "Formal company logo" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.logos.in.app", label: "App logo" },
      ],
      outputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.logos.out.documents", label: "Logo on documents" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.logos.out.sidebar", label: "Logo in the sidebar" },
      ],
      titleKey: "cases.put_your_company_letterhead_on_every_document.step.logos.title",
      titleDefault: "Upload your two logos",
      whatKey: "cases.put_your_company_letterhead_on_every_document.step.logos.what",
      whatDefault:
        "Open Settings on the Company & documents tab. Under Logos, drop the logo the team sees into Logo in the app (sidebar), and your formal logo into Logo on documents. PNG, JPG, SVG and WebP all work. Leave the document slot empty and documents print the app logo instead. Only an admin can change this tab.",
      whyKey: "cases.put_your_company_letterhead_on_every_document.step.logos.why",
      whyDefault:
        "The sidebar mark is often a small square icon, while a letter to an owner needs the full formal logo. Two slots let each place use the right one, and the fallback means no document goes out without a logo.",
      moduleLabel: "Settings",
      moduleLabelKey: "nav.settings",
      to: "/settings?tab=company",
    },
    {
      id: "details",
      icon: "Building2",
      inputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.details.in.name", label: "Legal name and address" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.details.in.numbers", label: "Registration and licence numbers" },
      ],
      outputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.details.out.block", label: "Company letterhead" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.details.out.contact", label: "Phone, email and website" },
      ],
      titleKey: "cases.put_your_company_letterhead_on_every_document.step.details.title",
      titleDefault: "Enter the company details",
      whatKey: "cases.put_your_company_letterhead_on_every_document.step.details.what",
      whatDefault:
        "Under Company letterhead, fill in the legal company name, the address in up to three lines, one line of registration and licence numbers, and the phone, email and website. Type them exactly as they should print, for example CA License #1234567, EIN 12-3456789 or USt-IdNr. DE123456789, HRB 12345, then click Save company details. The letterhead appears once a legal name or a document logo is saved; the app logo alone does not switch it on.",
      whyKey: "cases.put_your_company_letterhead_on_every_document.step.details.why",
      whyDefault:
        "Owners and lenders check the legal name and the licence or tax numbers against the contract, and some send back paperwork that lacks them. Every country prints different numbers in a different order, so these lines are free text and print word for word.",
      moduleLabel: "Settings",
      moduleLabelKey: "nav.settings",
      to: "/settings?tab=company",
    },
    {
      id: "appearance",
      icon: "PenTool",
      inputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.appearance.in.style", label: "House style" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.appearance.in.paper", label: "Paper size in use" },
      ],
      outputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.appearance.out.layout", label: "Document appearance" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.appearance.out.footer", label: "Footer line" },
      ],
      titleKey: "cases.put_your_company_letterhead_on_every_document.step.appearance.title",
      titleDefault: "Set how the pages look",
      whatKey: "cases.put_your_company_letterhead_on_every_document.step.appearance.what",
      whatDefault:
        "Further down the same tab, under How your documents look, set the Header position to left, centre or right, keep Print the company letterhead on the first page switched on, pick the heading colour, add a footer line if you want one, choose Show page numbers and the paper size, then click Save.",
      whyKey: "cases.put_your_company_letterhead_on_every_document.step.appearance.why",
      whyDefault:
        "One set of choices applies to every PDF the app prints, so the RFI, the payment application and the transmittal look as if they came from the same office rather than from three different templates.",
      moduleLabel: "Settings",
      moduleLabelKey: "nav.settings",
      to: "/settings?tab=company",
    },
    {
      id: "preview",
      icon: "Eye",
      inputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.preview.in.saved", label: "Saved company details" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.preview.in.appearance", label: "Saved document appearance" },
      ],
      outputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.preview.out.sample", label: "Sample PDF" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.preview.out.checked", label: "Checked letterhead" },
      ],
      titleKey: "cases.put_your_company_letterhead_on_every_document.step.preview.title",
      titleDefault: "Check the preview and the sample PDF",
      whatKey: "cases.put_your_company_letterhead_on_every_document.step.preview.what",
      whatDefault:
        "Read the preview headed Top of page 1, as printed, then click Open sample PDF. The server prints the sample exactly as it will print a real document, from what you have saved, so check the logo size, the address lines and the numbers there and fix anything before the first real document goes out.",
      whyKey: "cases.put_your_company_letterhead_on_every_document.step.preview.why",
      whyDefault:
        "A screen preview can hide a logo that prints too small or an address that wraps onto a fourth line. Checking one sample now is cheaper than recalling a batch of documents that went out wrong.",
      moduleLabel: "Settings",
      moduleLabelKey: "nav.settings",
      to: "/settings?tab=company",
    },
    {
      id: "rfi",
      icon: "FileOutput",
      inputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.rfi.in.rfi", label: "Open RFI" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.rfi.in.letterhead", label: "Checked letterhead" },
      ],
      outputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.rfi.out.pdf", label: "RFI PDF on the letterhead" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.rfi.out.later", label: "Small logo on later pages" },
      ],
      titleKey: "cases.put_your_company_letterhead_on_every_document.step.rfi.title",
      titleDefault: "Export an RFI on the letterhead",
      whatKey: "cases.put_your_company_letterhead_on_every_document.step.rfi.what",
      whatDefault:
        "Open any RFI from the list and click Export PDF. Page 1 carries your formal logo and the company details, and every later page carries the small logo, so a single loose page still shows who sent it.",
      whyKey: "cases.put_your_company_letterhead_on_every_document.step.rfi.why",
      whyDefault:
        "The RFI travels furthest: to the architect, the engineer and often the owner. It is the quickest real test that the letterhead holds up on a live document and not only on the sample.",
      moduleLabel: "RFIs",
      moduleLabelKey: "rfi.title",
      to: "/projects/:projectId/rfi",
    },
    {
      id: "others",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.others.in.application", label: "Payment application" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.others.in.letterhead", label: "Company letterhead" },
      ],
      outputs: [
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.others.out.pdf", label: "Payment application PDF" },
        { labelKey: "cases.put_your_company_letterhead_on_every_document.step.others.out.set", label: "One letterhead on every document" },
      ],
      titleKey: "cases.put_your_company_letterhead_on_every_document.step.others.title",
      titleDefault: "Send the other documents the same way",
      whatKey: "cases.put_your_company_letterhead_on_every_document.step.others.what",
      whatDefault:
        "On the contract, open a payment application, download its PDF and check that it carries the same letterhead. The cover sheet in the closeout package and the cover of a file transmittal print from the same settings, so there is nothing to set up again. When the address or a licence number changes, change it once in Settings and the next export picks it up; PDFs already sent are not re-rendered.",
      whyKey: "cases.put_your_company_letterhead_on_every_document.step.others.why",
      whyDefault:
        "Owners and lenders read these documents side by side. When every one carries the same name, address and numbers, nobody has to ask whether the payment application and the transmittal came from the same company, and a firm that requires its letterhead on everything gets it without anyone remembering to.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
  ],
};

export default playbook;
