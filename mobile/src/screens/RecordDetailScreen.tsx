import React, { useState } from "react";
import { Alert, Image, Text, StyleSheet } from "react-native";
import { useFocusEffect } from "../useFocus";
import { decideRecord, getRecord, mediaUrl, type MoneyRecord, type User } from "../api";
import { Btn, Card, Label, Row, Screen, Sub, TopBar } from "../components/ui";
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
  const isManager = user.role === "owner" || user.role === "manager";

  const reload = async () => {
    try {
      setRec(await getRecord(id));
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);

  const decide = async (approve: boolean) => {
    setBusy(true);
    try {
      setRec(await decideRecord(id, approve));
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
            <Text style={styles.line}>{rec.kind} · {rec.status}</Text>
            <Label>Amount</Label>
            <Text style={styles.big}>{rec.amount.toLocaleString()} {rec.currency}</Text>
            <Label>Category</Label>
            <Text style={styles.line}>{rec.category || "—"}</Text>
            <Label>By</Label>
            <Text style={styles.line}>{rec.created_by_name || rec.created_by}</Text>
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
              <Btn title="Reject" variant="danger" disabled={busy} onPress={() => decide(false)} />
            </Row>
          )}
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  line: { color: colors.text, marginTop: 2 },
  big: { color: colors.text, fontSize: 22, fontWeight: "700" },
  photo: { width: "100%", height: 220, borderRadius: 12, marginTop: 8, backgroundColor: colors.cardAlt },
});
