import type { components } from "./schema";

type Schemas = components["schemas"];

export type User = Schemas["UserOut"];
export type UserSettings = Schemas["UserSettingsOut"];
export type SettingsUpdate = Schemas["SettingsUpdateIn"];
export type LoginResponse = Schemas["LoginOut"];
export type Session = Schemas["SessionOut"];
export type MfaSetup = Schemas["MfaSetupOut"];
export type RecoveryCodes = Schemas["MfaEnableOut"];
export type Message = Schemas["MessageOut"];

export type Asset = Schemas["AssetOut"];
export type AssetList = Schemas["AssetListOut"];
export type AssetDetail = Schemas["AssetDetailOut"];
export type MarketOverview = Schemas["MarketOverviewOut"];
export type DataStatus = Schemas["DataStatus"];

export type Currency = UserSettings["base_currency"];
export type Locale = UserSettings["locale"];
export type SortKey = NonNullable<
  NonNullable<import("./schema").operations["list_assets_api_v1_market_assets_get"]["parameters"]["query"]>["sort"]
>;

export type AssetBrief = Schemas["AssetBriefOut"];
export type Exchange = Schemas["ExchangeOut"];
export type Portfolio = Schemas["PortfolioOut"];
export type TxType = Schemas["TxType"];
export type Transaction = Schemas["TransactionOut"];
export type TransactionInput = Schemas["TransactionIn"];
export type TransactionList = Schemas["TransactionListOut"];
export type PortfolioSummary = Schemas["SummaryOut"];
export type Position = Schemas["PositionOut"];
export type Performance = Schemas["PerformanceOut"];
export type SeriesPoint = Schemas["SeriesPoint"];
export type Insight = Schemas["InsightOut"];
export type InsightList = Schemas["InsightsOut"];
export type CsvPreview = Schemas["CsvPreviewOut"];
export type CsvCommit = Schemas["CsvCommitOut"];

export type Analysis = Schemas["AnalysisOut"];
export type AnalysisSnapshot = Schemas["Snapshot"];
export type Trend = Schemas["TrendOut"];
export type Level = Schemas["LevelOut"];
export type Timeframe = Analysis["timeframe"];
export type Watchlist = Schemas["WatchlistOut"];

export type Signal = Schemas["SignalOut"];
export type SignalList = Schemas["SignalListOut"];
export type SignalClass = Signal["classification"];
export type SignalHistoryPoint = Schemas["SignalHistoryPoint"];
export type Strategy = Schemas["StrategyOut"];
export type Alert = Schemas["AlertOut"];
export type AlertInput = Schemas["AlertIn"];
export type AlertType = Schemas["AlertType"];
export type NotificationItem = Schemas["NotificationOut"];
export type NotificationList = Schemas["NotificationListOut"];
