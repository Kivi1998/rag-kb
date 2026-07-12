package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.ragcore.model.QueryEvent;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class OpenAiCompatibleAnswerGeneratorTest {

    @Test
    void parsesOpenAiSseDeltaAndStopsAtDone() throws Exception {
        String upstream = "data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n"
                + "data: {\"choices\":[{\"delta\":{\"content\":\"第一段\"}}]}\n\n"
                + "data: {\"choices\":[{\"delta\":{\"content\":\"第二段\"}}]}\n\n"
                + "data: {\"model\":\"test-chat\",\"choices\":[],\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":6}}\n\n"
                + "data: [DONE]\n\n"
                + "data: {\"choices\":[{\"delta\":{\"content\":\"不得出现\"}}]}\n\n";
        List<QueryEvent> events = new ArrayList<>();

        OpenAiCompatibleAnswerGenerator.StreamUsage usage = OpenAiCompatibleAnswerGenerator.parseSse(
                new ByteArrayInputStream(upstream.getBytes(StandardCharsets.UTF_8)),
                new ObjectMapper(), events::add);

        assertEquals(List.of("第一段", "第二段"), events.stream().map(QueryEvent::content).toList());
        assertEquals(6, usage.outputCharacters());
        assertEquals("test-chat", usage.model());
        assertEquals(12, usage.promptTokens());
        assertEquals(6, usage.completionTokens());
    }
}
