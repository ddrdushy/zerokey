"use client";

// Slice 85 — AutoCount upload. Shared upload UI lives in
// ``CsvAccountingUpload`` (Slice 98) so the three CSV-driven
// accounting connectors don't triplicate the page.

import { CsvAccountingUpload } from "@/components/connectors/CsvAccountingUpload";

export default function UploadAutoCountPage() {
  return <CsvAccountingUpload variant="autocount" />;
}
