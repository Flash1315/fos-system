import React, { useState } from "react";
import { Alert, Image, Text, StyleSheet } from "react-native";
import { useFocusEffect } from "../useFocus";
import { decideRecord, getRecord, mediaUrl, type MoneyRecord, type User } from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Card, Label, Row, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen, statusColor } from "../format";
import { colors } from "../theme";

export function RecordDetailScreen({
  id,
  user,
  busy,
  setBusy,
  onBack,
}: {
  id: number;
  user: User;
  busy: boolean;
  setBusy: (v: boolean) => void;
  onBack: () => void;
}) {
  const [rec, setRec] = useState<MoneyRecord | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const isManager = user.role === "owner" || user.role === "manager";

  const reload = async () => {
    try {
      setRec(await getRecord(id));
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);

  const decide = async (approve: boolean, note = "") => {
    setBusy(true);
    try {
      setRec(await decideRecord(id, approve, note));
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen scroll>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Record #{id}</Text>
      {!rec ? (
        <Sub>Loading…</Sub>
      ) : (
        <>
          <Card>
            <Label>Kind / status</Label>
            <Text style={styles.line}>
              {rec.kind} · <Text style={{ color: statusColor(rec.status) }}>{rec.status}</Text>
            </Text>
            <Label>Amount</Label>
            <Text style={styles.big}>{formatMoney(rec.amount, rec.currency)}</Text>
            <Label>Category</Label>
            <Text style={styles.line}>{rec.category || "—"}</Text>
            <Label>By</Label>
            <Text style={styles.line}>{rec.created_by_name || rec.created_by} · {formatWhen(rec.created_at)}</Text>
            {!!rec.client_name && (
              <>
                <Label>Client</Label>
                <Text style={styles.line}>{rec.client_name} · {rec.payment_method || "—"}</Text>
              </>
            )}
            {(rec.liters != null || rec.odometer != null) && (
              <>
                <Label>Fuel</Label>
                <Text style={styles.line}>
                  {rec.liters ?? "—"} L · odo {rec.odometer ?? "—"}
                </Text>
              </>
            )}
            <Label>Comment</Label>
            <Text style={styles.line}>{rec.comment || "—"}</Text>
            {!!rec.decided_at && (
              <>
                <Label>Decided</Label>
                <Text style={styles.line}>{formatWhen(rec.decided_at)}</Text>
              </>
            )}
          </Card>
          {!!rec.photo_url && (
            <Card>
              <Label>Receipt</Label>
              <Image source={{ uri: mediaUrl(rec.photo_url) }} style={styles.photo} />
            </Card>
          )}
          {isManager && rec.status === "pending" && (
            <Row>
              <Btn title="Approve" disabled={busy} onPress={() => decide(true)} />
              <Btn title="Reject" variant="danger" disabled={busy} onPress={() => setRejectOpen(true)} />
            </Row>
          )}
        </>
      )}
      <NoteModal
        visible={rejectOpen}
        title="Reject record"
        onCancel={() => setRejectOpen(false)}
        onSubmit={async (note) => {
          setRejectOpen(false);
          await decide(false, note);
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  line: { color: colors.text, marginTop: 2 },
  big: { color: colors.text, fontSize: 22, fontWeight: "700" },
  photo: { width: "100%", height: 220, borderRadius: 12, marginTop: 8, backgroundColor: colors.cardAlt },
});
