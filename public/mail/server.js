import { ImapFlow } from "imapflow";
import { simpleParser } from "mailparser";
import nodemailer from "nodemailer";

const MAIL_HOST = "mail.mscteam.live";

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).end();
  }

  const { action, email, password, uid, to, subject, text } = req.body;

  // LOGIN
  if (action === "login") {
    const test = new ImapFlow({
      host: MAIL_HOST,
      port: 993,
      secure: true,
      auth: { user: email, pass: password },
    });
    try {
      await test.connect();
      await test.logout();
      return res.json({ ok: true });
    } catch {
      return res.status(401).json({ error: "login failed" });
    }
  }

  const imap = new ImapFlow({
    host: MAIL_HOST,
    port: 993,
    secure: true,
    auth: { user: email, pass: password },
  });

  await imap.connect();
  await imap.mailboxOpen("INBOX");

  // INBOX
  if (action === "inbox") {
    const list = [];
    for await (let msg of imap.fetch("1:*", { envelope: true })) {
      list.push({
        uid: msg.uid,
        subject: msg.envelope.subject,
        from: msg.envelope.from?.[0]?.address,
        date: msg.envelope.date,
      });
    }
    await imap.logout();
    return res.json(list.reverse());
  }

  // READ
  if (action === "read") {
    const msg = await imap.fetchOne(uid, { source: true });
    const parsed = await simpleParser(msg.source);
    await imap.logout();
    return res.json({
      subject: parsed.subject,
      from: parsed.from?.text,
      html: parsed.html,
      text: parsed.text,
    });
  }

  // DELETE
  if (action === "delete") {
    await imap.messageDelete(uid);
    await imap.expunge();
    await imap.logout();
    return res.json({ ok: true });
  }

  // SEND
  if (action === "send") {
    const transporter = nodemailer.createTransport({
      host: MAIL_HOST,
      port: 465,
      secure: true,
      auth: { user: email, pass: password },
    });

    await transporter.sendMail({
      from: email,
      to,
      subject,
      text,
    });

    return res.json({ ok: true });
  }

  await imap.logout();
  res.status(400).end();
}
