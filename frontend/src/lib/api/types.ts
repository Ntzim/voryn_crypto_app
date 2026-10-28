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
