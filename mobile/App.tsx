import React, { useEffect, useState } from "react";
import {
  clearToken,
  getToken,
  me,
  saveToken,
  type User,
} from "./src/api";
import { Loading } from "./src/components/ui";
import { AuthScreen } from "./src/screens/AuthScreen";
import { HomeScreen } from "./src/screens/HomeScreen";
import { CreateScreen } from "./src/screens/CreateScreen";
import { ApproveScreen } from "./src/screens/ApproveScreen";
import { InviteScreen } from "./src/screens/InviteScreen";
import { TeamScreen } from "./src/screens/TeamScreen";
import { ReportsScreen } from "./src/screens/ReportsScreen";
import { RecordDetailScreen } from "./src/screens/RecordDetailScreen";
import { LedgerScreen } from "./src/screens/LedgerScreen";
import { TransferScreen } from "./src/screens/TransferScreen";
import { PayoutScreen } from "./src/screens/PayoutScreen";
import { PayoutHistoryScreen } from "./src/screens/PayoutHistoryScreen";
import { BalancesScreen } from "./src/screens/BalancesScreen";

type Screen =
  | "boot"
  | "auth"
  | "home"
  | "create"
  | "approve"
  | "invite"
  | "team"
  | "reports"
  | "ledger"
  | "transfer"
  | "payout"
  | "payoutHistory"
  | "balances"
  | "record";

export default function App() {
  const [screen, setScreen] = useState<Screen>("boot");
  const [user, setUser] = useState<User | null>(null);
  const [busy, setBusy] = useState(false);
  const [recordId, setRecordId] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const token = await getToken();
        if (!token) {
          setScreen("auth");
          return;
        }
        const u = await me();
        setUser(u);
        setScreen("home");
      } catch {
        await clearToken();
        setScreen("auth");
      }
    })();
  }, []);

  if (screen === "boot") return <Loading />;

  if (screen === "auth") {
    return (
      <AuthScreen
        busy={busy}
        setBusy={setBusy}
        onDone={async (token, u) => {
          await saveToken(token);
          setUser(u);
          setScreen("home");
        }}
      />
    );
  }

  if (screen === "create" && user) {
    return (
      <CreateScreen
        busy={busy}
        setBusy={setBusy}
        onBack={() => setScreen("home")}
        onCreated={() => setScreen("home")}
      />
    );
  }

  if (screen === "approve" && user) {
    return (
      <ApproveScreen
        busy={busy}
        setBusy={setBusy}
        onBack={() => setScreen("home")}
        onRecord={(id) => {
          setRecordId(id);
          setScreen("record");
        }}
      />
    );
  }

  if (screen === "invite" && user) {
    return (
      <InviteScreen
        busy={busy}
        setBusy={setBusy}
        currentRole={user.role}
        onBack={() => setScreen("home")}
        onDone={() => setScreen("home")}
      />
    );
  }

  if (screen === "team" && user) {
    return (
      <TeamScreen
        busy={busy}
        setBusy={setBusy}
        currentUser={user}
        onBack={() => setScreen("home")}
      />
    );
  }

  if (screen === "reports" && user) {
    return <ReportsScreen onBack={() => setScreen("home")} />;
  }

  if (screen === "ledger" && user) {
    return (
      <LedgerScreen
        onBack={() => setScreen("home")}
        onRecord={(id) => {
          setRecordId(id);
          setScreen("record");
        }}
      />
    );
  }

  if (screen === "transfer" && user) {
    return (
      <TransferScreen
        busy={busy}
        setBusy={setBusy}
        onBack={() => setScreen("home")}
        onDone={() => setScreen("home")}
      />
    );
  }

  if (screen === "payout" && user) {
    return (
      <PayoutScreen
        busy={busy}
        setBusy={setBusy}
        onBack={() => setScreen("home")}
        onDone={() => setScreen("home")}
      />
    );
  }

  if (screen === "payoutHistory" && user) {
    return <PayoutHistoryScreen user={user} onBack={() => setScreen("home")} />;
  }

  if (screen === "balances" && user) {
    return <BalancesScreen onBack={() => setScreen("home")} />;
  }

  if (screen === "record" && user && recordId != null) {
    return (
      <RecordDetailScreen
        id={recordId}
        user={user}
        busy={busy}
        setBusy={setBusy}
        onBack={() => setScreen("home")}
      />
    );
  }

  return (
    <HomeScreen
      user={user}
      onCreate={() => setScreen("create")}
      onApprove={() => setScreen("approve")}
      onInvite={() => setScreen("invite")}
      onTeam={() => setScreen("team")}
      onReports={() => setScreen("reports")}
      onLedger={() => setScreen("ledger")}
      onTransfer={() => setScreen("transfer")}
      onPayout={() => setScreen("payout")}
      onPayoutHistory={() => setScreen("payoutHistory")}
      onBalances={() => setScreen("balances")}
      onRecord={(id) => {
        setRecordId(id);
        setScreen("record");
      }}
      onLogout={async () => {
        await clearToken();
        setUser(null);
        setScreen("auth");
      }}
    />
  );
}
