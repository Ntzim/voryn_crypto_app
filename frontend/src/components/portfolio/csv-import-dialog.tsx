"use client";

import { cn } from "cn";
import { Download, FileUp, LoaderCircle, TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { isApiError } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";
import { useTransactionMutations } from "@/lib/portfolio-queries";
import { usePreferences } from "@/lib/queries";

const MAX_BYTES = 1_000_000;
const STATUS = {
  valid: { label: "Pronta", className: "text-success" },
  duplicate: { label: "Já importada", className: "text-muted-foreground" },
  error: { label: "Erro", className: "text-destructive" },
} as const;

export function CsvImportDialog({
  open,
  onOpenChange,
  portfolioId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  portfolioId: string;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && <CsvImport portfolioId={portfolioId} onDone={() => onOpenChange(false)} />}
    </Dialog>
  );
}

function CsvImport({ portfolioId, onDone }: { portfolioId: string; onDone: () => void }) {
  const { locale, timeZone } = usePreferences();
  const { preview, commit } = useTransactionMutations(portfolioId);
  const [content, setContent] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [fileError, setFileError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const data = preview.data;

  const pick = async (file: File | undefined) => {
    setFileError(null);
    if (!file) return;
    if (file.size > MAX_BYTES) return setFileError("O arquivo deve ter no máximo 1 MB.");
    const text = await file.text();
    setContent(text);
    setFileName(file.name);
    preview.mutate(text);
  };

  const importRows = () => {
    if (!content) return;
    commit.mutate(
      { content, skipInvalid: true },
      {
        onSuccess: (result) => {
          toast.success(`${result.imported} transação(ões) importada(s).`);
          onDone();
        },
      },
    );
  };

  const error = fileError ?? (preview.error || commit.error ? (isApiError(preview.error ?? commit.error) ? (preview.error ?? commit.error)!.message : "Não foi possível processar o arquivo.") : null);

  return (
    <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-3xl">
      <DialogHeader>
        <DialogTitle>Importar transações (CSV)</DialogTitle>
        <DialogDescription>
          Use o modelo da Voryn. Separador <code>;</code> ou <code>,</code>, números como 1.234,56 ou 1234.56 e datas
          AAAA-MM-DD HH:MM ou DD/MM/AAAA HH:MM (no seu fuso, {timeZone.replaceAll("_", " ")}). Linhas já importadas são
          ignoradas automaticamente.
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" asChild>
          <a href="/api/v1/portfolios/csv-template" download>
            <Download /> Baixar modelo
          </a>
        </Button>
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          onChange={(e) => pick(e.target.files?.[0])}
          aria-label="Arquivo CSV"
        />
        <Button size="sm" onClick={() => input.current?.click()} disabled={preview.isPending}>
          {preview.isPending ? <LoaderCircle className="animate-spin" /> : <FileUp />}
          {fileName ? "Escolher outro arquivo" : "Escolher arquivo"}
        </Button>
        {fileName && <span className="self-center text-xs text-muted-foreground">{fileName}</span>}
      </div>

      {error && (
        <Alert variant="destructive" className="border-destructive/30 bg-destructive/10">
          <TriangleAlert />
          <AlertDescription className="text-destructive">{error}</AlertDescription>
        </Alert>
      )}

      {data && (
        <>
          <div className="num flex flex-wrap gap-4 text-sm">
            <span className="text-success">{data.valid} prontas</span>
            <span className="text-muted-foreground">{data.duplicates} já importadas</span>
            <span className={cn(data.errors ? "text-destructive" : "text-muted-foreground")}>{data.errors} com erro</span>
          </div>
          <div className="max-h-80 overflow-auto rounded-lg border border-border">
            <table className="num w-full text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border text-muted-foreground">
                  <th className="px-3 py-2 text-left font-medium">Linha</th>
                  <th className="px-3 py-2 text-left font-medium">Situação</th>
                  <th className="px-3 py-2 text-left font-medium">Data</th>
                  <th className="px-3 py-2 text-left font-medium">Tipo</th>
                  <th className="px-3 py-2 text-left font-medium">Ativo</th>
                  <th className="px-3 py-2 text-right font-medium">Quantidade</th>
                  <th className="px-3 py-2 text-right font-medium">Preço</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.line} className="border-b border-border align-top last:border-0">
                    <td className="px-3 py-2 text-muted-foreground">{row.line}</td>
                    <td className={cn("px-3 py-2 font-medium", STATUS[row.status].className)}>
                      {STATUS[row.status].label}
                      {row.errors.map((e) => (
                        <div key={e} className="font-normal">{e}</div>
                      ))}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">{row.executed_at ? formatDateTime(row.executed_at, locale, timeZone) : "—"}</td>
                    <td className="px-3 py-2">{row.type}</td>
                    <td className="px-3 py-2">{row.asset}</td>
                    <td className="px-3 py-2 text-right">{row.quantity}</td>
                    <td className="px-3 py-2 text-right">{row.unit_price ? `${row.unit_price} ${row.quote_currency}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.errors > 0 && (
            <p className="text-xs text-muted-foreground">
              Linhas com erro não serão importadas. Corrija-as no arquivo e importe novamente quando quiser — as já
              importadas não serão duplicadas.
            </p>
          )}
        </>
      )}

      <DialogFooter>
        <Button variant="ghost" onClick={onDone}>Cancelar</Button>
        <Button onClick={importRows} disabled={!data || data.valid === 0 || commit.isPending}>
          {commit.isPending && <LoaderCircle className="animate-spin" />}
          Importar {data?.valid ?? 0} transação(ões)
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
