import assert from 'node:assert/strict';
import test from 'node:test';
import { practiceSwitch } from '../api/voice.js';

test('Spanish practice starts on request and stays on while practicing', () => {
  for (const heard of ["Let's practice Spanish", 'can you teach me Spanish?', 'I want to learn some Spanish', 'Spanish lesson please']) {
    assert.equal(practiceSwitch(heard, false), 'on', heard);
  }
  assert.equal(practiceSwitch('Yo quiero un café, por favor.', true), 'on');
  assert.equal(practiceSwitch('How do I say I am hungry?', true), 'on');
});

test('Spanish practice stops only when it is on', () => {
  for (const heard of ['stop practicing', "Okay I'm done with Spanish", 'back to English please', 'end the lesson']) {
    assert.equal(practiceSwitch(heard, true), 'off', heard);
    assert.equal(practiceSwitch(heard, false), null, heard);
  }
});

test('ordinary questions are not practice', () => {
  for (const heard of ["What's the weather tomorrow?", "What's the Spanish word for dog?", 'Start a 25 minute focus timer']) {
    assert.equal(practiceSwitch(heard, false), null, heard);
  }
});
