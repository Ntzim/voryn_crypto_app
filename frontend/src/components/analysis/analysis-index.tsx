"use client";

import { Star } from "lucide-react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/common/page-header";
import { EmptyState } from "@/components/common/states";
import { AssetList } from "@/components/market/asset-list";
import { AssetPicker } from "@/components/portfolio/asset-picker";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useWatchlists } from "@/lib/analysis-queries";
import { useAssets, usePreferences } from "@/lib/queries";

export function AnalysisIndex() {
  const router = useRouter();
  const { locale } = usePreferences();
  const watchlists = useWatchlists();
  const favorites = watchlists.data?.find((w) => w.is_default);
  const favoriteAssets = useAssets({
    currency: "USD",
    q: "",
    sort: "rank",
    order: "asc",
    page: 1,
    pageSize: 50,
    watchlistId: favorites?.id,
  });
  const top = useAssets({ currency: "USD", q: "", sort: "rank", order: "asc", page: 1, pageSize: 12 });

  return (
    <>
      <PageHeader
        title="Análise de Ativos"
        description="Candles de 15 minutos a 1 semana, indicadores técnicos, tendência e níveis de suporte e resistência."
      />
      <div className="mb-6 max-w-md">
        <AssetPicker value={null} onChange={(asset) => router.push(`/analise/${asset.slug}`)} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="font-heading text-sm font-medium">Favoritos</CardTitle>
          </CardHeader>
          <CardContent>
            {favorites && favorites.asset_ids.length === 0 ? (
              <EmptyState
                icon={Star}
                title="Nenhum favorito ainda"
                description="Use a estrela no Mercado ou o botão “Listas” em um ativo para acompanhá-lo aqui."
                className="py-6"
              />
            ) : (
              <AssetList
                assets={favorites ? favoriteAssets.data?.items : undefined}
                currency="USD"
                locale={locale}
                loading={!favorites || favoriteAssets.isPending || favoriteAssets.isPlaceholderData}
                rows={4}
                hrefBase="/analise"
              />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="font-heading text-sm font-medium">Maiores por capitalização</CardTitle>
          </CardHeader>
          <CardContent>
            <AssetList assets={top.data?.items} currency="USD" locale={locale} loading={top.isPending} rows={8} showRank hrefBase="/analise" />
          </CardContent>
        </Card>
      </div>
      <p className="mt-4 text-xs text-subtle-foreground">
        Preços em USD. Indicadores são calculados de forma determinística sobre candles fechados e não constituem recomendação.
      </p>
    </>
  );
}
