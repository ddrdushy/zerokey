"use client";

// Slice 98 — SQL Account upload. Shared UI in CsvAccountingUpload.

import { CsvAccountingUpload } from "@/components/connectors/CsvAccountingUpload";

export default function UploadSqlAccountPage() {
  return <CsvAccountingUpload variant="sql_account" />;
}
