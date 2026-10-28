import { redirect } from "next/navigation";

// Unauthenticated visitors are redirected to /entrar by src/proxy.ts before reaching this.
export default function Home() {
  redirect("/dashboard");
}
